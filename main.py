"""
main.py - Sistema de Realidad Aumentada con Cámara y Animaciones 3D
Proyecto: VisualCam AR
Versión: 2.10 - Soporte para múltiples cámaras
"""

import os
import sys
import time
import json
import threading
import base64
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, render_template, request, jsonify, Response, send_from_directory
import webview

# ============================================================
#  CONFIGURACIÓN DEL PROYECTO
# ============================================================

class Config:
    """Configuración global del proyecto"""
    # Servidor
    HOST = '127.0.0.1'
    PORT = 5000
    DEBUG = False
    
    # Directorios (solo los necesarios)
    BASE_DIR = Path(__file__).parent
    TEMPLATES_DIR = BASE_DIR / 'templates'
    STATIC_DIR = BASE_DIR / 'static'
    MODULOS_DIR = TEMPLATES_DIR / 'modulos'
    MODULOS_ANIDADOS_DIR = MODULOS_DIR / 'modulos'  # Para estructura anidada
    ANIMACIONES_DIR = BASE_DIR / 'animaciones'
    DATOS_DIR = BASE_DIR / 'datos'
    MODELOS_DIR = BASE_DIR / 'modelos'
    
    # Archivos
    HISTORIAL_FILE = ANIMACIONES_DIR / 'historial.json'
    OBJETOS_AR_FILE = DATOS_DIR / 'objetos_ar.json'
    
    # Configuración de cámara
    RESOLUCIONES = ['640x480', '1280x720', '1920x1080']
    FPS_MIN = 1
    FPS_MAX = 120
    EFECTOS_VALIDOS = ['ninguno', 'gris', 'negativo', 'sepia', 'bordes', 'desenfoque', 'cartoon']
    FORMATOS_VIDEO = ['mp4', 'avi', 'mov']
    
    # AR (Realidad Aumentada)
    MAX_OBJETOS_AR = 50
    DISTANCIA_OBJETO = 2.0
    
    # Múltiples cámaras
    MAX_CAMARAS = 10

# ============================================================
#  INICIALIZACIÓN DE FLASK
# ============================================================

app = Flask(__name__,
            template_folder=str(Config.TEMPLATES_DIR),
            static_folder=str(Config.STATIC_DIR))

# ============================================================
#  ESTADO GLOBAL DE LA APLICACIÓN
# ============================================================

class AppState:
    """Estado global de la aplicación"""
    def __init__(self):
        self.camara_activa = False
        self.captura = None
        self.camara_id = 0  # Índice de la cámara actual
        self.frame_actual = None
        self.historial_animaciones = []
        self.objetos_ar = []
        self.camaras_disponibles = []  # Lista de cámaras detectadas
        self.configuracion = {
            'fps': 30,
            'duracion': 5,
            'resolucion': '640x480',
            'efecto': 'ninguno',
            'formato_salida': 'mp4',
            'camara_id': 0,
            'camara_nombre': 'Cámara 0'
        }
    
    def cargar_datos(self):
        """Carga datos guardados previamente"""
        if Config.HISTORIAL_FILE.exists():
            try:
                with open(Config.HISTORIAL_FILE, 'r', encoding='utf-8') as f:
                    self.historial_animaciones = json.load(f)
                print(f"📂 Cargadas {len(self.historial_animaciones)} animaciones")
            except Exception as e:
                print(f"⚠️ Error al cargar historial: {e}")
        
        if Config.OBJETOS_AR_FILE.exists():
            try:
                with open(Config.OBJETOS_AR_FILE, 'r', encoding='utf-8') as f:
                    self.objetos_ar = json.load(f)
                print(f"🎯 Cargados {len(self.objetos_ar)} objetos AR")
            except Exception as e:
                print(f"⚠️ Error al cargar objetos AR: {e}")
    
    def guardar_datos(self):
        """Guarda los datos actuales"""
        try:
            with open(Config.HISTORIAL_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.historial_animaciones, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Error al guardar historial: {e}")
        
        try:
            with open(Config.OBJETOS_AR_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.objetos_ar, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Error al guardar objetos AR: {e}")

# Instancia global del estado
estado = AppState()

# ============================================================
#  FUNCIONES DE UTILIDAD - CÁMARAS
# ============================================================

def detectar_camaras():
    """Detecta todas las cámaras disponibles en el sistema"""
    camaras = []
    
    for i in range(Config.MAX_CAMARAS):
        try:
            # Probar diferentes backends
            for backend in [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_V4L2, cv2.CAP_ANY]:
                try:
                    cap = cv2.VideoCapture(i, backend)
                    if cap.isOpened():
                        # Leer un frame para verificar que funciona
                        ret, frame = cap.read()
                        if ret and frame is not None:
                            nombre = f"Cámara {i}"
                            # Intentar obtener nombre más descriptivo
                            nombre_backend = cap.getBackendName() if hasattr(cap, 'getBackendName') else ''
                            camaras.append({
                                'id': i,
                                'nombre': nombre,
                                'backend': nombre_backend,
                                'activa': True,
                                'ancho': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                                'alto': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                                'fps': int(cap.get(cv2.CAP_PROP_FPS))
                            })
                        cap.release()
                        break
                except:
                    continue
        except Exception as e:
            continue
    
    # Si no se detectaron cámaras, intentar con la cámara por defecto
    if not camaras:
        try:
            cap = cv2.VideoCapture(0)
            if cap.isOpened():
                camaras.append({
                    'id': 0,
                    'nombre': 'Cámara por defecto',
                    'backend': 'default',
                    'activa': True,
                    'ancho': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                    'alto': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                    'fps': int(cap.get(cv2.CAP_PROP_FPS))
                })
                cap.release()
        except:
            pass
    
    estado.camaras_disponibles = camaras
    return camaras

def abrir_camara(camara_id=0):
    """Abre una cámara específica"""
    captura = None
    
    # Intentar abrir con diferentes backends
    for backend in [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_V4L2, cv2.CAP_ANY]:
        try:
            cap = cv2.VideoCapture(camara_id, backend)
            if cap.isOpened():
                captura = cap
                break
        except:
            continue
    
    if captura is None:
        captura = cv2.VideoCapture(camara_id)
    
    if not captura.isOpened():
        return None
    
    # Configurar resolución
    resolucion = estado.configuracion['resolucion']
    if resolucion == '640x480':
        captura.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        captura.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    elif resolucion == '1280x720':
        captura.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        captura.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    elif resolucion == '1920x1080':
        captura.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        captura.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    
    captura.set(cv2.CAP_PROP_FPS, estado.configuracion['fps'])
    
    return captura

# ============================================================
#  RUTAS PRINCIPALES
# ============================================================

@app.route('/')
def home():
    """Página de inicio - Presentación VisualCam AR"""
    return render_template('index.html')

@app.route('/index')
def index():
    """Página de inicio (alias)"""
    return render_template('index.html')

@app.route('/modulos/main')
def modulo_main():
    """Sirve el módulo principal de AR"""
    archivo_normal = Config.MODULOS_DIR / 'main.html'
    archivo_anidado = Config.MODULOS_ANIDADOS_DIR / 'main.html'
    
    if archivo_normal.exists():
        return render_template('modulos/main.html')
    elif archivo_anidado.exists():
        return render_template('modulos/modulos/main.html')
    else:
        return jsonify({
            'error': True,
            'mensaje': 'Módulo main.html no encontrado',
            'rutas_buscadas': [str(archivo_normal), str(archivo_anidado)]
        }), 404

@app.route('/modulos/camara')
@app.route('/modulos/modulos/camara.html')
def modulo_camara():
    """Sirve el módulo de cámara"""
    archivo_normal = Config.MODULOS_DIR / 'camara.html'
    archivo_anidado = Config.MODULOS_ANIDADOS_DIR / 'camara.html'
    
    if archivo_anidado.exists():
        return render_template('modulos/modulos/camara.html')
    elif archivo_normal.exists():
        return render_template('modulos/camara.html')
    else:
        return jsonify({
            'error': True,
            'mensaje': 'Módulo camara.html no encontrado',
            'rutas_buscadas': [str(archivo_normal), str(archivo_anidado)]
        }), 404

@app.route('/modulos/insertar_objeto')
@app.route('/modulos/modulos/insertar_objeto.html')
def modulo_insertar_objeto():
    """Sirve el módulo de inserción de objetos 3D"""
    archivo_normal = Config.MODULOS_DIR / 'insertar_objeto.html'
    archivo_anidado = Config.MODULOS_ANIDADOS_DIR / 'insertar_objeto.html'
    
    if archivo_anidado.exists():
        return render_template('modulos/modulos/insertar_objeto.html')
    elif archivo_normal.exists():
        return render_template('modulos/insertar_objeto.html')
    else:
        return jsonify({
            'error': True,
            'mensaje': 'Módulo insertar_objeto.html no encontrado',
            'rutas_buscadas': [str(archivo_normal), str(archivo_anidado)]
        }), 404

@app.route('/modulos/ubicacion')
@app.route('/modulos/modulos/ubicacion.html')
def modulo_ubicacion():
    """Sirve el módulo de ubicación GPS"""
    archivo_normal = Config.MODULOS_DIR / 'ubicacion.html'
    archivo_anidado = Config.MODULOS_ANIDADOS_DIR / 'ubicacion.html'
    
    if archivo_anidado.exists():
        return render_template('modulos/modulos/ubicacion.html')
    elif archivo_normal.exists():
        return render_template('modulos/ubicacion.html')
    else:
        return jsonify({
            'error': True,
            'mensaje': 'Módulo ubicacion.html no encontrado',
            'rutas_buscadas': [str(archivo_normal), str(archivo_anidado)]
        }), 404

@app.route('/modulos/efectos')
def modulo_efectos():
    """Sirve el módulo de efectos"""
    archivo_normal = Config.MODULOS_DIR / 'efectos.html'
    archivo_anidado = Config.MODULOS_ANIDADOS_DIR / 'efectos.html'
    
    if archivo_normal.exists():
        return render_template('modulos/efectos.html')
    elif archivo_anidado.exists():
        return render_template('modulos/modulos/efectos.html')
    else:
        return jsonify({
            'error': True,
            'mensaje': 'Módulo efectos.html no encontrado'
        }), 404

@app.route('/modulos/historial')
def modulo_historial():
    """Sirve el módulo de historial"""
    archivo_normal = Config.MODULOS_DIR / 'historial.html'
    archivo_anidado = Config.MODULOS_ANIDADOS_DIR / 'historial.html'
    
    if archivo_normal.exists():
        return render_template('modulos/historial.html')
    elif archivo_anidado.exists():
        return render_template('modulos/modulos/historial.html')
    else:
        return jsonify({
            'error': True,
            'mensaje': 'Módulo historial.html no encontrado'
        }), 404

@app.route('/modulos/<modulo>')
def modulo_generico(modulo):
    """Ruta genérica para módulos (fallback)"""
    modulos_validos = ['main', 'camara', 'insertar_objeto', 'ubicacion', 'efectos', 'historial', 'grabacion']
    
    if modulo not in modulos_validos:
        return jsonify({
            'error': True,
            'mensaje': f'Módulo "{modulo}" no válido',
            'modulos_disponibles': modulos_validos
        }), 404
    
    archivo_normal = Config.MODULOS_DIR / f'{modulo}.html'
    archivo_anidado = Config.MODULOS_ANIDADOS_DIR / f'{modulo}.html'
    
    if archivo_anidado.exists():
        return render_template(f'modulos/modulos/{modulo}.html')
    elif archivo_normal.exists():
        return render_template(f'modulos/{modulo}.html')
    else:
        return jsonify({
            'error': True,
            'mensaje': f'Módulo "{modulo}" no encontrado',
            'rutas_buscadas': [str(archivo_normal), str(archivo_anidado)]
        }), 404

@app.route('/static/<path:filename>')
def servir_static(filename):
    """Sirve archivos estáticos (CSS, JS, imágenes)"""
    return send_from_directory(str(Config.STATIC_DIR), filename)

@app.route('/animaciones/<path:filename>')
def servir_animacion(filename):
    """Sirve archivos de animaciones (imágenes/videos)"""
    return send_from_directory(str(Config.ANIMACIONES_DIR), filename)

# ============================================================
#  RUTAS DE LA API - CÁMARA
# ============================================================

@app.route('/api/health', methods=['GET'])
def health():
    """Verifica el estado de la aplicación"""
    return jsonify({
        'status': 'ok',
        'camara_activa': estado.camara_activa,
        'camara_id': estado.camara_id,
        'animaciones': len(estado.historial_animaciones),
        'objetos_ar': len(estado.objetos_ar),
        'ar_soporte': True,
        'version': '2.10',
        'camaras_disponibles': len(estado.camaras_disponibles)
    }), 200

@app.route('/api/camaras/detectar', methods=['GET'])
def detectar_camaras_api():
    """Detecta todas las cámaras disponibles"""
    camaras = detectar_camaras()
    return jsonify({
        'success': True,
        'camaras': camaras,
        'total': len(camaras)
    })

@app.route('/api/camara/iniciar', methods=['POST'])
def iniciar_camara():
    """Inicia la cámara para captura de video"""
    global estado
    
    try:
        data = request.get_json() or {}
        camara_id = data.get('camara_id', estado.configuracion.get('camara_id', 0))
        
        if estado.camara_activa:
            # Detener cámara actual primero
            if estado.captura and estado.captura.isOpened():
                estado.captura.release()
                estado.captura = None
            estado.camara_activa = False
        
        # Actualizar ID de cámara
        estado.camara_id = camara_id
        estado.configuracion['camara_id'] = camara_id
        
        # Abrir cámara
        captura = abrir_camara(camara_id)
        
        if captura is None or not captura.isOpened():
            return jsonify({'success': False, 'mensaje': f'No se pudo acceder a la cámara {camara_id}'}), 500
        
        estado.captura = captura
        estado.camara_activa = True
        
        # Obtener información de la cámara
        nombre_camara = f"Cámara {camara_id}"
        for cam in estado.camaras_disponibles:
            if cam['id'] == camara_id:
                nombre_camara = cam.get('nombre', nombre_camara)
                break
        
        estado.configuracion['camara_nombre'] = nombre_camara
        
        return jsonify({
            'success': True,
            'mensaje': f'Cámara {camara_id} iniciada correctamente',
            'camara_id': camara_id,
            'camara_nombre': nombre_camara,
            'fps': estado.configuracion['fps'],
            'resolucion': estado.configuracion['resolucion']
        })
        
    except Exception as e:
        return jsonify({'success': False, 'mensaje': f'Error al iniciar cámara: {str(e)}'}), 500

@app.route('/api/camara/detener', methods=['POST'])
def detener_camara():
    """Detiene la cámara"""
    global estado
    
    try:
        if estado.captura and estado.captura.isOpened():
            estado.captura.release()
        
        estado.camara_activa = False
        estado.captura = None
        return jsonify({'success': True, 'mensaje': 'Cámara detenida correctamente'})
        
    except Exception as e:
        return jsonify({'success': False, 'mensaje': f'Error al detener cámara: {str(e)}'}), 500

@app.route('/api/camara/cambiar', methods=['POST'])
def cambiar_camara():
    """Cambia a otra cámara disponible"""
    global estado
    
    try:
        data = request.get_json()
        camara_id = data.get('camara_id')
        
        if camara_id is None:
            return jsonify({'success': False, 'mensaje': 'No se especificó ID de cámara'}), 400
        
        # Verificar que la cámara existe
        camara_existe = False
        for cam in estado.camaras_disponibles:
            if cam['id'] == camara_id:
                camara_existe = True
                break
        
        if not camara_existe:
            # Intentar detectar de nuevo
            detectar_camaras()
            for cam in estado.camaras_disponibles:
                if cam['id'] == camara_id:
                    camara_existe = True
                    break
        
        if not camara_existe:
            return jsonify({'success': False, 'mensaje': f'Cámara {camara_id} no disponible'}), 404
        
        # Detener cámara actual si está activa
        if estado.camara_activa:
            if estado.captura and estado.captura.isOpened():
                estado.captura.release()
            estado.camara_activa = False
            estado.captura = None
        
        # Abrir nueva cámara
        captura = abrir_camara(camara_id)
        
        if captura is None or not captura.isOpened():
            return jsonify({'success': False, 'mensaje': f'No se pudo abrir la cámara {camara_id}'}), 500
        
        estado.captura = captura
        estado.camara_id = camara_id
        estado.camara_activa = True
        estado.configuracion['camara_id'] = camara_id
        
        # Obtener nombre
        nombre_camara = f"Cámara {camara_id}"
        for cam in estado.camaras_disponibles:
            if cam['id'] == camara_id:
                nombre_camara = cam.get('nombre', nombre_camara)
                break
        estado.configuracion['camara_nombre'] = nombre_camara
        
        return jsonify({
            'success': True,
            'mensaje': f'Cambiado a cámara {camara_id}',
            'camara_id': camara_id,
            'camara_nombre': nombre_camara
        })
        
    except Exception as e:
        return jsonify({'success': False, 'mensaje': f'Error al cambiar cámara: {str(e)}'}), 500

@app.route('/api/camara/stream')
def video_stream_api():
    """Streaming de video desde la cámara (API)"""
    return video_stream()

@app.route('/video_stream')
def video_stream():
    """Streaming de video desde la cámara (legacy)"""
    def generate_frames():
        global estado
        
        # Esperar a que la cámara esté activa
        timeout = 30
        while not estado.camara_activa and timeout > 0:
            time.sleep(0.1)
            timeout -= 1
        
        if not estado.camara_activa:
            # Si no hay cámara, enviar un frame negro
            blank = np.zeros((480, 640, 3), dtype=np.uint8)
            # Agregar texto indicando cámara inactiva
            cv2.putText(blank, "Camara inactiva", (200, 240), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 100), 2)
            ret, buffer = cv2.imencode('.jpg', blank)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            return
        
        # Obtener información de la cámara para overlay
        cam_id = estado.camara_id
        cam_nombre = estado.configuracion.get('camara_nombre', f'Cámara {cam_id}')
        
        while estado.camara_activa and estado.captura and estado.captura.isOpened():
            try:
                ret, frame = estado.captura.read()
                
                if not ret:
                    time.sleep(0.1)
                    continue
                
                # Aplicar efecto si está configurado
                if estado.configuracion['efecto'] != 'ninguno':
                    frame = aplicar_efecto(frame, estado.configuracion['efecto'])
                
                # Agregar overlay con información de la cámara
                cv2.putText(frame, f"Camara: {cam_nombre}", (10, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                cv2.putText(frame, f"ID: {cam_id}", (10, 55), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
                cv2.putText(frame, f"FPS: {estado.configuracion['fps']}", (10, 80), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
                
                estado.frame_actual = frame.copy()
                
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                
                if not ret:
                    continue
                
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                
                time.sleep(1.0 / estado.configuracion['fps'])
                
            except Exception as e:
                print(f"⚠️ Error en stream: {e}")
                time.sleep(0.1)
                continue
    
    return Response(generate_frames(), 
                   mimetype='multipart/x-mixed-replace; boundary=frame')

def aplicar_efecto(frame, efecto):
    """Aplica efectos visuales al frame"""
    if efecto == 'gris':
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    elif efecto == 'negativo':
        return cv2.bitwise_not(frame)
    elif efecto == 'sepia':
        sepia_filter = np.array([[0.272, 0.534, 0.131],
                                [0.349, 0.686, 0.168],
                                [0.393, 0.769, 0.189]])
        sepia_frame = cv2.transform(frame, sepia_filter)
        return np.clip(sepia_frame, 0, 255).astype(np.uint8)
    elif efecto == 'bordes':
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        return cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
    elif efecto == 'desenfoque':
        return cv2.GaussianBlur(frame, (15, 15), 0)
    elif efecto == 'cartoon':
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.medianBlur(gray, 5)
        edges = cv2.adaptiveThreshold(gray, 255, 
                                    cv2.ADAPTIVE_THRESH_MEAN_C, 
                                    cv2.THRESH_BINARY, 9, 9)
        color = cv2.bilateralFilter(frame, 9, 300, 300)
        cartoon = cv2.bitwise_and(color, color, mask=edges)
        return cartoon
    return frame

# ============================================================
#  RUTAS DE LA API - ANIMACIONES (COMPATIBILIDAD)
# ============================================================

@app.route('/obtener_configuracion', methods=['GET'])
def obtener_configuracion_legacy():
    return jsonify({
        'success': True,
        'configuracion': estado.configuracion,
        'camara_activa': estado.camara_activa,
        'camara_id': estado.camara_id,
        'camaras_disponibles': estado.camaras_disponibles
    })

@app.route('/listar_animaciones', methods=['GET'])
def listar_animaciones_legacy():
    return jsonify({
        'success': True,
        'animaciones': estado.historial_animaciones,
        'total': len(estado.historial_animaciones)
    })

@app.route('/iniciar_camara', methods=['POST'])
def iniciar_camara_legacy():
    return iniciar_camara()

@app.route('/detener_camara', methods=['POST'])
def detener_camara_legacy():
    return detener_camara()

@app.route('/capturar_imagen', methods=['POST'])
def capturar_imagen_legacy():
    return capturar_imagen()

@app.route('/grabar_video', methods=['POST'])
def grabar_video_legacy():
    return grabar_video()

@app.route('/configurar_animacion', methods=['POST'])
def configurar_animacion_legacy():
    return actualizar_configuracion()

@app.route('/eliminar_animacion', methods=['POST'])
def eliminar_animacion_legacy():
    return eliminar_animacion()

# ============================================================
#  RUTAS DE LA API - ANIMACIONES (NUEVAS)
# ============================================================

@app.route('/api/animaciones/capturar', methods=['POST'])
def capturar_imagen():
    global estado
    
    try:
        if estado.frame_actual is None:
            return jsonify({'success': False, 'mensaje': 'No hay frame disponible'}), 400
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        nombre_archivo = f"captura_{timestamp}.jpg"
        ruta_completa = Config.ANIMACIONES_DIR / nombre_archivo
        
        cv2.imwrite(str(ruta_completa), estado.frame_actual)
        
        _, buffer = cv2.imencode('.jpg', estado.frame_actual)
        img_base64 = base64.b64encode(buffer).decode('utf-8')
        
        animacion = {
            'nombre': nombre_archivo,
            'tipo': 'imagen',
            'fecha': timestamp,
            'ruta': str(ruta_completa),
            'efecto': estado.configuracion['efecto'],
            'camara_id': estado.camara_id,
            'camara_nombre': estado.configuracion.get('camara_nombre', f'Cámara {estado.camara_id}')
        }
        estado.historial_animaciones.append(animacion)
        estado.guardar_datos()
        
        return jsonify({
            'success': True,
            'mensaje': 'Imagen capturada correctamente',
            'archivo': nombre_archivo,
            'imagen_base64': f"data:image/jpeg;base64,{img_base64}",
            'animacion': animacion
        })
        
    except Exception as e:
        return jsonify({'success': False, 'mensaje': f'Error al capturar imagen: {str(e)}'}), 500

@app.route('/api/animaciones/grabar', methods=['POST'])
def grabar_video():
    global estado
    
    try:
        if not estado.camara_activa or estado.captura is None:
            return jsonify({'success': False, 'mensaje': 'La cámara no está activa'}), 400
        
        data = request.get_json() or {}
        duracion = data.get('duracion', estado.configuracion['duracion'])
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        nombre_archivo = f"video_{timestamp}.mp4"
        ruta_completa = Config.ANIMACIONES_DIR / nombre_archivo
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        
        if estado.frame_actual is not None:
            height, width = estado.frame_actual.shape[:2]
        else:
            return jsonify({'success': False, 'mensaje': 'No hay frame disponible'}), 400
        
        out = cv2.VideoWriter(str(ruta_completa), fourcc, 
                             estado.configuracion['fps'], 
                             (width, height))
        
        if not out.isOpened():
            return jsonify({'success': False, 'mensaje': 'Error al crear el video'}), 500
        
        frames_grabados = 0
        frames_necesarios = int(duracion * estado.configuracion['fps'])
        
        for _ in range(frames_necesarios):
            if not estado.camara_activa:
                break
                
            ret, frame = estado.captura.read()
            
            if not ret:
                break
            
            if estado.configuracion['efecto'] != 'ninguno':
                frame = aplicar_efecto(frame, estado.configuracion['efecto'])
            
            out.write(frame)
            frames_grabados += 1
            
            time.sleep(1.0 / estado.configuracion['fps'])
        
        out.release()
        
        if frames_grabados == 0:
            return jsonify({'success': False, 'mensaje': 'No se grabó ningún frame'}), 500
        
        animacion = {
            'nombre': nombre_archivo,
            'tipo': 'video',
            'fecha': timestamp,
            'ruta': str(ruta_completa),
            'duracion': duracion,
            'frames': frames_grabados,
            'efecto': estado.configuracion['efecto'],
            'camara_id': estado.camara_id,
            'camara_nombre': estado.configuracion.get('camara_nombre', f'Cámara {estado.camara_id}')
        }
        estado.historial_animaciones.append(animacion)
        estado.guardar_datos()
        
        return jsonify({
            'success': True,
            'mensaje': f'Video grabado correctamente ({frames_grabados} frames)',
            'archivo': nombre_archivo,
            'animacion': animacion
        })
        
    except Exception as e:
        return jsonify({'success': False, 'mensaje': f'Error al grabar video: {str(e)}'}), 500

@app.route('/api/animaciones/listar', methods=['GET'])
def listar_animaciones():
    return jsonify({
        'success': True,
        'animaciones': estado.historial_animaciones,
        'total': len(estado.historial_animaciones)
    })

@app.route('/api/animaciones/eliminar', methods=['POST'])
def eliminar_animacion():
    global estado
    
    try:
        data = request.get_json()
        nombre = data.get('nombre')
        
        if not nombre:
            return jsonify({'success': False, 'mensaje': 'Nombre de animación no proporcionado'}), 400
        
        animacion_a_eliminar = None
        for animacion in estado.historial_animaciones:
            if animacion['nombre'] == nombre:
                animacion_a_eliminar = animacion
                break
        
        if not animacion_a_eliminar:
            return jsonify({'success': False, 'mensaje': 'Animación no encontrada'}), 404
        
        ruta = Path(animacion_a_eliminar['ruta'])
        if ruta.exists():
            ruta.unlink()
        
        estado.historial_animaciones.remove(animacion_a_eliminar)
        estado.guardar_datos()
        
        return jsonify({
            'success': True,
            'mensaje': f'Animación {nombre} eliminada correctamente'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'mensaje': f'Error al eliminar animación: {str(e)}'}), 500

# ============================================================
#  RUTAS DE LA API - CONFIGURACIÓN
# ============================================================

@app.route('/api/configuracion/obtener', methods=['GET'])
def obtener_configuracion():
    return jsonify({
        'success': True,
        'configuracion': estado.configuracion,
        'camara_activa': estado.camara_activa,
        'camara_id': estado.camara_id,
        'camaras_disponibles': estado.camaras_disponibles
    })

@app.route('/api/configuracion/actualizar', methods=['POST'])
def actualizar_configuracion():
    global estado
    
    try:
        data = request.get_json()
        
        if 'fps' in data:
            fps = int(data['fps'])
            if Config.FPS_MIN <= fps <= Config.FPS_MAX:
                estado.configuracion['fps'] = fps
                if estado.captura and estado.captura.isOpened():
                    estado.captura.set(cv2.CAP_PROP_FPS, fps)
        
        if 'duracion' in data:
            duracion = float(data['duracion'])
            if 1 <= duracion <= 60:
                estado.configuracion['duracion'] = duracion
        
        if 'resolucion' in data:
            if data['resolucion'] in Config.RESOLUCIONES:
                estado.configuracion['resolucion'] = data['resolucion']
                if estado.camara_activa and estado.captura:
                    w, h = map(int, data['resolucion'].split('x'))
                    estado.captura.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                    estado.captura.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        
        if 'efecto' in data:
            if data['efecto'] in Config.EFECTOS_VALIDOS:
                estado.configuracion['efecto'] = data['efecto']
        
        if 'formato_salida' in data:
            if data['formato_salida'] in Config.FORMATOS_VIDEO:
                estado.configuracion['formato_salida'] = data['formato_salida']
        
        if 'camara_id' in data:
            camara_id = int(data['camara_id'])
            # Verificar que la cámara existe
            camara_existe = False
            for cam in estado.camaras_disponibles:
                if cam['id'] == camara_id:
                    camara_existe = True
                    break
            
            if camara_existe:
                estado.configuracion['camara_id'] = camara_id
                estado.camara_id = camara_id
                
                # Si la cámara está activa, cambiar
                if estado.camara_activa:
                    # Detener y reiniciar con nueva cámara
                    if estado.captura and estado.captura.isOpened():
                        estado.captura.release()
                    captura = abrir_camara(camara_id)
                    if captura and captura.isOpened():
                        estado.captura = captura
                        estado.camara_activa = True
                    else:
                        estado.camara_activa = False
                        estado.captura = None
        
        return jsonify({
            'success': True,
            'configuracion': estado.configuracion
        })
        
    except Exception as e:
        return jsonify({'success': False, 'mensaje': f'Error al actualizar configuración: {str(e)}'}), 500

# ============================================================
#  RUTAS DE LA API - REALIDAD AUMENTADA (AR)
# ============================================================

@app.route('/api/ar/objetos', methods=['GET'])
def ar_obtener_objetos():
    return jsonify({
        'success': True,
        'objetos': estado.objetos_ar,
        'total': len(estado.objetos_ar)
    })

@app.route('/api/ar/guardar', methods=['POST'])
def ar_guardar_objeto():
    global estado
    
    try:
        data = request.get_json()
        
        if not data.get('nombre') or not data.get('posicion'):
            return jsonify({'success': False, 'mensaje': 'Datos incompletos'}), 400
        
        data['id'] = len(estado.objetos_ar) + 1
        data['fecha_creacion'] = datetime.now().isoformat()
        
        estado.objetos_ar.append(data)
        estado.guardar_datos()
        
        return jsonify({
            'success': True,
            'mensaje': 'Objeto AR guardado correctamente',
            'objeto': data
        })
        
    except Exception as e:
        return jsonify({'success': False, 'mensaje': f'Error al guardar objeto AR: {str(e)}'}), 500

@app.route('/api/ar/eliminar/<int:objeto_id>', methods=['DELETE'])
def ar_eliminar_objeto(objeto_id):
    global estado
    
    try:
        objeto_a_eliminar = None
        for obj in estado.objetos_ar:
            if obj.get('id') == objeto_id:
                objeto_a_eliminar = obj
                break
        
        if not objeto_a_eliminar:
            return jsonify({'success': False, 'mensaje': 'Objeto no encontrado'}), 404
        
        estado.objetos_ar.remove(objeto_a_eliminar)
        estado.guardar_datos()
        
        return jsonify({
            'success': True,
            'mensaje': f'Objeto AR {objeto_id} eliminado correctamente'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'mensaje': f'Error al eliminar objeto AR: {str(e)}'}), 500

@app.route('/api/ar/limpiar', methods=['POST'])
def ar_limpiar_objetos():
    global estado
    
    try:
        estado.objetos_ar = []
        estado.guardar_datos()
        return jsonify({
            'success': True,
            'mensaje': 'Todos los objetos AR eliminados'
        })
    except Exception as e:
        return jsonify({'success': False, 'mensaje': f'Error al limpiar objetos AR: {str(e)}'}), 500

# ============================================================
#  RUTAS DE LA API - MODELOS 3D
# ============================================================

@app.route('/api/modelos/guardar', methods=['POST'])
def guardar_modelo():
    """Guarda un modelo 3D subido por el usuario"""
    try:
        if 'modelo' not in request.files:
            return jsonify({'success': False, 'mensaje': 'No se encontró el archivo'}), 400
        
        file = request.files['modelo']
        if file.filename == '':
            return jsonify({'success': False, 'mensaje': 'Nombre de archivo vacío'}), 400
        
        # Crear directorio para modelos
        if not Config.MODELOS_DIR.exists():
            Config.MODELOS_DIR.mkdir(parents=True)
        
        # Generar nombre único
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        nombre_archivo = f"{timestamp}_{file.filename}"
        ruta_completa = Config.MODELOS_DIR / nombre_archivo
        file.save(str(ruta_completa))
        
        # Obtener metadatos
        nombre = request.form.get('nombre', file.filename.split('.')[0])
        tipo = request.form.get('tipo', 'custom')
        color = request.form.get('color', '#4a7cf7')
        escala = float(request.form.get('escala', 1.0))
        
        modelo_info = {
            'id': int(time.time() * 1000),
            'nombre': nombre,
            'archivo': nombre_archivo,
            'url': f'/modelos/{nombre_archivo}',
            'tipo': tipo,
            'color': color,
            'escala': escala,
            'formato': file.filename.split('.')[-1].upper(),
            'fecha': timestamp,
        }
        
        return jsonify({
            'success': True,
            'mensaje': 'Modelo guardado correctamente',
            'modelo': modelo_info
        })
        
    except Exception as e:
        return jsonify({'success': False, 'mensaje': f'Error al guardar modelo: {str(e)}'}), 500

@app.route('/modelos/<path:filename>')
def servir_modelo(filename):
    """Sirve archivos de modelos 3D"""
    return send_from_directory(str(Config.MODELOS_DIR), filename)

@app.route('/api/modelos/listar', methods=['GET'])
def listar_modelos():
    """Lista todos los modelos guardados"""
    try:
        if not Config.MODELOS_DIR.exists():
            return jsonify({'success': True, 'modelos': []})
        
        modelos = []
        for archivo in Config.MODELOS_DIR.iterdir():
            if archivo.suffix.lower() in ['.glb', '.gltf', '.obj']:
                modelos.append({
                    'nombre': archivo.stem,
                    'archivo': archivo.name,
                    'url': f'/modelos/{archivo.name}',
                    'tamaño': archivo.stat().st_size,
                })
        
        return jsonify({'success': True, 'modelos': modelos})
        
    except Exception as e:
        return jsonify({'success': False, 'mensaje': str(e)}), 500

# ============================================================
#  FUNCIÓN PRINCIPAL
# ============================================================

def main():
    """Función principal del programa"""
    print("=" * 70)
    print("🎬 VISUALCAM AR - Sistema de Realidad Aumentada v2.10")
    print("🔄 Soporte para múltiples cámaras")
    print("=" * 70)
    print(f"📂 Directorio base: {Config.BASE_DIR}")
    print("=" * 70)
    
    # Verificar directorios
    print("\n📁 Verificando estructura de carpetas:")
    
    directorios_requeridos = [
        ('templates', Config.TEMPLATES_DIR),
        ('templates/modulos', Config.MODULOS_DIR),
        ('templates/modulos/modulos', Config.MODULOS_ANIDADOS_DIR),
        ('static', Config.STATIC_DIR),
        ('animaciones', Config.ANIMACIONES_DIR),
        ('datos', Config.DATOS_DIR),
        ('modelos', Config.MODELOS_DIR)
    ]
    
    for nombre, ruta in directorios_requeridos:
        if ruta.exists():
            print(f"   ✅ {nombre} encontrado")
        else:
            print(f"   ⚠️ {nombre} NO encontrado (creando...)")
            try:
                ruta.mkdir(parents=True, exist_ok=True)
                print(f"   📁 {nombre} creado automáticamente")
            except:
                pass
    
    # Verificar archivos importantes
    print("\n📁 Verificando archivos HTML:")
    
    index_path = Config.TEMPLATES_DIR / 'index.html'
    main_path = Config.MODULOS_DIR / 'main.html'
    main_anidado_path = Config.MODULOS_ANIDADOS_DIR / 'main.html'
    camara_path = Config.MODULOS_DIR / 'camara.html'
    camara_anidado_path = Config.MODULOS_ANIDADOS_DIR / 'camara.html'
    insertar_path = Config.MODULOS_DIR / 'insertar_objeto.html'
    insertar_anidado_path = Config.MODULOS_ANIDADOS_DIR / 'insertar_objeto.html'
    ubicacion_path = Config.MODULOS_DIR / 'ubicacion.html'
    ubicacion_anidado_path = Config.MODULOS_ANIDADOS_DIR / 'ubicacion.html'
    
    if index_path.exists():
        print(f"   ✅ index.html encontrado")
    else:
        print(f"   ⚠️ index.html NO encontrado")
    
    if main_path.exists():
        print(f"   ✅ main.html encontrado en: {main_path}")
    elif main_anidado_path.exists():
        print(f"   ✅ main.html encontrado en (estructura anidada): {main_anidado_path}")
    else:
        print(f"   ⚠️ main.html NO encontrado")
    
    if camara_path.exists():
        print(f"   ✅ camara.html encontrado en: {camara_path}")
    elif camara_anidado_path.exists():
        print(f"   ✅ camara.html encontrado en (estructura anidada): {camara_anidado_path}")
    else:
        print(f"   ⚠️ camara.html NO encontrado")
    
    if insertar_path.exists():
        print(f"   ✅ insertar_objeto.html encontrado en: {insertar_path}")
    elif insertar_anidado_path.exists():
        print(f"   ✅ insertar_objeto.html encontrado en (estructura anidada): {insertar_anidado_path}")
    else:
        print(f"   ⚠️ insertar_objeto.html NO encontrado")
    
    if ubicacion_path.exists():
        print(f"   ✅ ubicacion.html encontrado en: {ubicacion_path}")
    elif ubicacion_anidado_path.exists():
        print(f"   ✅ ubicacion.html encontrado en (estructura anidada): {ubicacion_anidado_path}")
    else:
        print(f"   ⚠️ ubicacion.html NO encontrado")
    
    # Detectar cámaras
    print("\n📷 Detectando cámaras disponibles...")
    camaras = detectar_camaras()
    if camaras:
        print(f"   ✅ {len(camaras)} cámara(s) detectada(s):")
        for cam in camaras:
            print(f"      - ID {cam['id']}: {cam['nombre']} (backend: {cam.get('backend', 'N/A')})")
    else:
        print("   ⚠️ No se detectaron cámaras")
    
    # Cargar datos guardados
    estado.cargar_datos()
    
    # Iniciar servidor Flask
    print("\n🌐 Iniciando servidor web...")
    print(f"   URL: http://{Config.HOST}:{Config.PORT}")
    print(f"   Página principal: http://{Config.HOST}:{Config.PORT}/")
    print(f"   Módulo AR: http://{Config.HOST}:{Config.PORT}/modulos/main")
    print(f"   Módulo Cámara: http://{Config.HOST}:{Config.PORT}/modulos/camara")
    print(f"   Módulo Objetos 3D: http://{Config.HOST}:{Config.PORT}/modulos/insertar_objeto")
    print(f"   Módulo Ubicación: http://{Config.HOST}:{Config.PORT}/modulos/ubicacion")
    print(f"   Módulo Efectos: http://{Config.HOST}:{Config.PORT}/modulos/efectos")
    print(f"   Módulo Historial: http://{Config.HOST}:{Config.PORT}/modulos/historial")
    print(f"   Health check: http://{Config.HOST}:{Config.PORT}/api/health")
    print(f"   Detectar cámaras: http://{Config.HOST}:{Config.PORT}/api/camaras/detectar")
    
    print("\n📌 También disponibles (con extensión .html):")
    print(f"   http://{Config.HOST}:{Config.PORT}/modulos/modulos/camara.html")
    print(f"   http://{Config.HOST}:{Config.PORT}/modulos/modulos/insertar_objeto.html")
    print(f"   http://{Config.HOST}:{Config.PORT}/modulos/modulos/ubicacion.html")
    
    def iniciar_flask():
        app.run(host=Config.HOST, 
                port=Config.PORT, 
                debug=Config.DEBUG, 
                use_reloader=False, 
                threaded=True)
    
    hilo_flask = threading.Thread(target=iniciar_flask)
    hilo_flask.daemon = True
    hilo_flask.start()
    
    time.sleep(2)
    
    print("\n🪟 Abriendo interfaz VisualCam AR...")
    webview.create_window(
        title="VisualCam AR - Realidad Aumentada v2.10",
        url=f"http://{Config.HOST}:{Config.PORT}",
        width=1280,
        height=800,
        resizable=True,
        min_size=(1024, 720),
        confirm_close=True
    )
    webview.start()
    
    print("\n💾 Guardando datos...")
    estado.guardar_datos()
    
    if estado.captura and estado.captura.isOpened():
        estado.captura.release()
    
    print("👋 Aplicación cerrada correctamente")
    sys.exit(0)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ Aplicación interrumpida por el usuario")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error fatal: {e}")
        sys.exit(1)