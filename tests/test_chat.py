"""Pruebas del sistema de mensajería en tiempo real con detección de estafas."""

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.chat_manager import ConnectionManager, normalize_phone, conversation_key
from app.main import create_app


# ============================================================================
# 1. PRUEBAS UNITARIAS DEL GESTOR DE CHAT
# ============================================================================

class TestNormalizePhone:
    def test_valid_phone_numbers(self):
        assert normalize_phone("+59170011223") == "+59170011223"
        assert normalize_phone("+54 11 1234 5678") == "+541112345678"
        assert normalize_phone("+34-612-345-678") == "+34612345678"
        assert normalize_phone("  +591 700 11 223  ") == "+59170011223"
        assert normalize_phone("77004938") == "+59177004938"

    def test_invalid_phone_numbers(self):
        with pytest.raises(ValueError):
            normalize_phone("123")  # muy corto
        with pytest.raises(ValueError):
            normalize_phone("+123")  # muy corto
        with pytest.raises(ValueError):
            normalize_phone("hola")
        with pytest.raises(ValueError):
            normalize_phone("")


class TestConversationKey:
    def test_key_is_symmetric(self):
        assert conversation_key("+591A", "+591B") == conversation_key("+591B", "+591A")

    def test_key_is_sorted(self):
        key = conversation_key("+591Z", "+591A")
        a, b = key.split("|")
        assert a <= b


class TestConnectionManager:
    def test_next_id_unique(self):
        mgr = ConnectionManager()
        ids = {mgr.next_id() for _ in range(100)}
        assert len(ids) == 100

    def test_is_online_without_connection(self):
        mgr = ConnectionManager()
        assert not mgr.is_online("+59170000000")

    def test_store_and_get_history(self):
        from app.chat_manager import ChatMessage
        mgr = ConnectionManager()
        msg = ChatMessage(
            id="test-1", remitente="+591A", destinatario="+591B",
            texto="Hola", timestamp=1000.0,
        )
        mgr.store_message(msg)
        history = mgr.get_history("+591A", "+591B")
        assert len(history) == 1
        assert history[0]["texto"] == "Hola"
        # Es simétrico
        assert mgr.get_history("+591B", "+591A") == history


# ============================================================================
# 2. PRUEBAS DE LA RUTA /chat
# ============================================================================

def test_chat_page_served(trained_artifact):
    with TestClient(create_app(trained_artifact[0])) as client:
        response = client.get("/chat")
        assert response.status_code == 200
        assert "Mensajería" in response.text or "chat" in response.text.lower()


def test_original_pages_still_work(trained_artifact):
    """La interfaz web original y la API de análisis siguen funcionando."""
    with TestClient(create_app(trained_artifact[0])) as client:
        assert client.get("/").status_code == 200
        assert "Mensaje Seguro" in client.get("/").text
        assert client.get("/estado").status_code == 200
        r = client.post("/analizar", json={"texto": "Hola, nos vemos mañana."})
        assert r.status_code == 200
        assert r.json()["etiqueta_modelo"] in ("legitimo", "fraudulento")


# ============================================================================
# 3. PRUEBAS WEBSOCKET DE MENSAJERÍA
# ============================================================================

def test_websocket_connect_and_receive_system_message(trained_artifact):
    """Un usuario puede conectarse y recibe un mensaje del sistema."""
    app = create_app(trained_artifact[0])
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat/+59170011223") as ws:
            data = ws.receive_json()
            assert data["tipo"] == "sistema"
            assert "+59170011223" in data["mensaje"]
            assert "+59170011223" in data["usuarios_online"]


def test_websocket_invalid_phone_rejected(trained_artifact):
    """Un número telefónico inválido no puede conectarse."""
    app = create_app(trained_artifact[0])
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/chat/invalid") as ws:
                ws.receive_json()


def test_two_users_exchange_messages(trained_artifact):
    """Dos usuarios intercambian mensajes y reciben las alertas ML."""
    app = create_app(trained_artifact[0])
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat/+59170000001") as ws1:
            sys1 = ws1.receive_json()
            assert sys1["tipo"] == "sistema"

            with client.websocket_connect("/ws/chat/+59170000002") as ws2:
                sys2 = ws2.receive_json()
                assert sys2["tipo"] == "sistema"

                # ws1 debería recibir una notificación de que ws2 se conectó
                notif = ws1.receive_json()
                assert notif["tipo"] == "usuario_conectado"
                assert "+59170000002" in notif["usuarios_online"]

                # ws1 envía un mensaje SEGURO a ws2
                ws1.send_json({
                    "tipo": "mensaje",
                    "destinatario": "+59170000002",
                    "texto": "Hola, nos vemos mañana para comer.",
                })

                # ws1 recibe confirmación del envío
                sent = ws1.receive_json()
                assert sent["tipo"] == "mensaje_enviado"
                assert sent["texto"] == "Hola, nos vemos mañana para comer."
                assert sent["etiqueta_modelo"] == "legitimo"
                assert sent["nivel"] == "bajo"

                # ws2 recibe el mensaje con la alerta de seguridad
                received = ws2.receive_json()
                assert received["tipo"] == "mensaje_recibido"
                assert received["texto"] == "Hola, nos vemos mañana para comer."
                assert received["etiqueta_modelo"] == "legitimo"
                assert received["nivel"] == "bajo"


def test_fraudulent_message_detected_in_chat(trained_artifact):
    """Un mensaje fraudulento enviado por chat dispara alertas de seguridad."""
    app = create_app(trained_artifact[0])
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat/+59170000001") as ws1:
            ws1.receive_json()  # sistema

            with client.websocket_connect("/ws/chat/+59170000002") as ws2:
                ws2.receive_json()  # sistema
                ws1.receive_json()  # usuario_conectado

                fraud_text = "URGENTE: Tu cuenta bancaria ha sido bloqueada. Transfiere tu contraseña ahora mismo para reactivarla."
                ws1.send_json({
                    "tipo": "mensaje",
                    "destinatario": "+59170000002",
                    "texto": fraud_text,
                })

                sent = ws1.receive_json()
                assert sent["tipo"] == "mensaje_enviado"
                assert sent["etiqueta_modelo"] == "fraudulento"
                assert sent["nivel"] == "alto"
                assert len(sent["senales"]) > 0
                assert len(sent["recomendaciones"]) > 0

                received = ws2.receive_json()
                assert received["tipo"] == "mensaje_recibido"
                assert received["etiqueta_modelo"] == "fraudulento"
                assert received["nivel"] == "alto"
                # Debe incluir señales como urgencia, credenciales, dinero
                signal_codes = {s["codigo"] for s in received["senales"]}
                assert "urgencia" in signal_codes or "credenciales" in signal_codes


def test_suspicious_message_with_prize(trained_artifact):
    """Un mensaje sospechoso con mención de premios se detecta correctamente."""
    app = create_app(trained_artifact[0])
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat/+59170000001") as ws1:
            ws1.receive_json()
            with client.websocket_connect("/ws/chat/+59170000002") as ws2:
                ws2.receive_json()
                ws1.receive_json()

                ws1.send_json({
                    "tipo": "mensaje",
                    "destinatario": "+59170000002",
                    "texto": "Ganaste un premio de 10.000 BS. Paga una tasa para cobrarlo en https://premio.example.com",
                })

                sent = ws1.receive_json()
                assert sent["tipo"] == "mensaje_enviado"
                signal_codes = {s["codigo"] for s in sent["senales"]}
                assert "premio" in signal_codes or "enlace" in signal_codes

                received = ws2.receive_json()
                assert received["tipo"] == "mensaje_recibido"
                assert len(received["senales"]) > 0


def test_empty_message_rejected(trained_artifact):
    """Un mensaje vacío es rechazado sin llegar al destinatario."""
    app = create_app(trained_artifact[0])
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat/+59170000001") as ws1:
            ws1.receive_json()
            ws1.send_json({
                "tipo": "mensaje",
                "destinatario": "+59170000002",
                "texto": "   ",
            })
            err = ws1.receive_json()
            assert err["tipo"] == "error"
            assert "vacío" in err["mensaje"]


def test_too_long_message_rejected(trained_artifact):
    """Un mensaje demasiado largo es rechazado."""
    app = create_app(trained_artifact[0])
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat/+59170000001") as ws1:
            ws1.receive_json()
            ws1.send_json({
                "tipo": "mensaje",
                "destinatario": "+59170000002",
                "texto": "A" * 5001,
            })
            err = ws1.receive_json()
            assert err["tipo"] == "error"
            assert "límite" in err["mensaje"] or "excede" in err["mensaje"]


def test_message_to_offline_user_stored(trained_artifact):
    """Un mensaje enviado a un usuario desconectado se guarda y se notifica."""
    app = create_app(trained_artifact[0])
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat/+59170000001") as ws1:
            ws1.receive_json()

            ws1.send_json({
                "tipo": "mensaje",
                "destinatario": "+59199999999",
                "texto": "Hola, estás ahí?",
            })

            sent = ws1.receive_json()
            assert sent["tipo"] == "mensaje_enviado"

            info = ws1.receive_json()
            assert info["tipo"] == "info"
            assert "no está conectado" in info["mensaje"]


def test_history_request(trained_artifact):
    """Un usuario puede solicitar el historial de una conversación."""
    app = create_app(trained_artifact[0])
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat/+59170000001") as ws1:
            ws1.receive_json()

            # Enviar un par de mensajes
            ws1.send_json({
                "tipo": "mensaje",
                "destinatario": "+59170000002",
                "texto": "Mensaje de prueba",
            })
            ws1.receive_json()  # mensaje_enviado
            ws1.receive_json()  # info (offline)

            # Solicitar historial
            ws1.send_json({
                "tipo": "historial",
                "destinatario": "+59170000002",
            })
            hist = ws1.receive_json()
            assert hist["tipo"] == "historial"
            assert hist["con"] == "+59170000002"
            assert len(hist["mensajes"]) >= 1
            assert hist["mensajes"][0]["texto"] == "Mensaje de prueba"


def test_self_message_rejected(trained_artifact):
    """No se permite enviarse un mensaje a uno mismo."""
    app = create_app(trained_artifact[0])
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat/+59170000001") as ws1:
            ws1.receive_json()
            ws1.send_json({
                "tipo": "mensaje",
                "destinatario": "+59170000001",
                "texto": "Hola yo",
            })
            err = ws1.receive_json()
            assert err["tipo"] == "error"
            assert "ti mismo" in err["mensaje"]

