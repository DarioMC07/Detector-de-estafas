"use strict";

/* ============================================================
   CHAT.JS — Cliente WebSocket para la mensajería de Mensaje Seguro
   ============================================================ */

// Estado global
let ws = null;
let myPhone = "";
let currentPeer = "";
let onlineUsers = [];
let conversations = {}; // { phone: [msg, ...] }

// Elementos del DOM
const loginScreen = document.getElementById("login-screen");
const chatScreen = document.getElementById("chat-screen");
const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const myPhoneInput = document.getElementById("my-phone");
const myPhoneDisplay = document.getElementById("my-phone-display");
const logoutBtn = document.getElementById("logout-btn");
const newChatForm = document.getElementById("new-chat-form");
const destPhoneInput = document.getElementById("dest-phone");
const contactsList = document.getElementById("contacts-list");
const onlineList = document.getElementById("online-list");
const noChat = document.getElementById("no-chat");
const activeChat = document.getElementById("active-chat");
const peerPhone = document.getElementById("peer-phone");
const peerStatus = document.getElementById("peer-status");
const chatArea = document.getElementById("chat-area");
const sendForm = document.getElementById("send-form");
const msgInput = document.getElementById("msg-input");
const backBtn = document.getElementById("back-btn");
const sidebar = document.querySelector(".chat-sidebar");
const chatMain = document.querySelector(".chat-main");


/* ---- Utilidades ---- */

function cleanPhone(raw) {
  let cleaned = raw.replace(/[\s\-().]/g, "").trim();
  if (cleaned && !cleaned.startsWith("+")) {
    if (cleaned.length === 8 && /^\d+$/.test(cleaned)) {
      cleaned = "+591" + cleaned;
    } else if (/^\d+$/.test(cleaned) && cleaned.length >= 7) {
      cleaned = "+" + cleaned;
    }
  }
  return cleaned;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function formatTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
}

function scrollToBottom() {
  chatArea.scrollTop = chatArea.scrollHeight;
}


/* ---- Conexión WebSocket ---- */

function connect(phone) {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${protocol}//${location.host}/ws/chat/${encodeURIComponent(phone)}`;
  ws = new WebSocket(url);

  ws.onopen = () => {
    myPhone = phone;
    loginScreen.hidden = true;
    chatScreen.hidden = false;
    myPhoneDisplay.textContent = phone;
    loginError.hidden = true;
    // Mobile: show sidebar by default
    sidebar.classList.remove("sidebar-hidden");
    chatMain.classList.add("main-hidden");
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    handleMessage(data);
  };

  ws.onclose = (event) => {
    if (event.code === 4000) {
      showLoginError("Número telefónico inválido. Usa formato internacional, ej: +59170011223");
    } else if (event.code === 4001) {
      showLoginError("Tu sesión fue reemplazada por otra conexión.");
    }
    // Intentar reconectar si fue una desconexión inesperada
    if (myPhone && event.code !== 4000 && event.code !== 4001) {
      setTimeout(() => {
        if (myPhone) connect(myPhone);
      }, 3000);
    }
  };

  ws.onerror = () => {
    showLoginError("No se pudo conectar con el servidor. Asegúrate de que la API esté en ejecución.");
  };
}

function disconnect() {
  myPhone = "";
  currentPeer = "";
  conversations = {};
  onlineUsers = [];
  if (ws) {
    ws.close();
    ws = null;
  }
  chatScreen.hidden = true;
  loginScreen.hidden = false;
  myPhoneInput.value = "";
  noChat.hidden = false;
  activeChat.hidden = true;
  chatArea.replaceChildren();
  renderContacts();
  renderOnline();
}


/* ---- Manejo de mensajes del servidor ---- */

function handleMessage(data) {
  switch (data.tipo) {
    case "sistema":
      updateOnline(data.usuarios_online || []);
      break;

    case "usuario_conectado":
      updateOnline(data.usuarios_online || []);
      // Si el usuario que se conectó es el peer actual, actualizar su estado
      if (data.telefono === currentPeer) {
        setPeerOnline(true);
      }
      break;

    case "usuario_desconectado":
      updateOnline(data.usuarios_online || []);
      if (data.telefono === currentPeer) {
        setPeerOnline(false);
      }
      break;

    case "mensaje_enviado":
      storeMessage(data);
      if (data.destinatario === currentPeer) {
        renderBubble(data, true);
        scrollToBottom();
      }
      renderContacts();
      break;

    case "mensaje_recibido":
      storeMessage(data);
      if (data.remitente === currentPeer) {
        renderBubble(data, false);
        scrollToBottom();
      }
      renderContacts();
      break;

    case "historial":
      loadHistory(data);
      break;

    case "error":
      appendSystemMessage(data.mensaje);
      break;

    case "info":
      appendSystemMessage(data.mensaje);
      break;

    case "pong":
      break;
  }
}


/* ---- Almacenamiento local de mensajes ---- */

function storeMessage(data) {
  const peer = data.remitente === myPhone ? data.destinatario : data.remitente;
  if (!conversations[peer]) conversations[peer] = [];
  // Evitar duplicados por ID
  if (!conversations[peer].some(m => m.id === data.id)) {
    conversations[peer].push(data);
  }
}

function loadHistory(data) {
  const peer = data.con;
  conversations[peer] = data.mensajes || [];
  if (peer === currentPeer) {
    renderAllMessages();
  }
  renderContacts();
}


/* ---- Renderizado de mensajes ---- */

function renderBubble(msg, isSent) {
  const bubble = document.createElement("div");
  bubble.className = `msg-bubble ${isSent ? "msg-sent" : "msg-received"}`;

  const textEl = document.createElement("div");
  textEl.className = "msg-text";
  textEl.textContent = msg.texto;
  bubble.appendChild(textEl);

  // Si es un mensaje recibido, mostrar alerta de seguridad
  if (!isSent && msg.etiqueta_modelo) {
    const alert = buildAlert(msg);
    if (alert) bubble.appendChild(alert);
  }

  const timeEl = document.createElement("span");
  timeEl.className = "msg-time";
  timeEl.textContent = formatTime(msg.timestamp);
  bubble.appendChild(timeEl);

  chatArea.appendChild(bubble);
}

function buildAlert(msg) {
  const nivel = msg.nivel || "bajo";
  const etiqueta = msg.etiqueta_modelo || "legitimo";
  const senales = msg.senales || [];
  const recomendaciones = msg.recomendaciones || [];
  const incertidumbre = msg.incertidumbre || false;

  const alert = document.createElement("div");
  alert.className = `msg-alert alert-${incertidumbre ? "medio" : nivel}`;

  const header = document.createElement("div");
  header.className = "alert-header";

  let icon, title;
  if (etiqueta === "fraudulento") {
    icon = "🚨";
    title = incertidumbre ? "POSIBLE ESTAFA (Riesgo Moderado)" : "POSIBLE ESTAFA";
  } else if (incertidumbre) {
    icon = "⚠️";
    title = "RESULTADO INCIERTO";
  } else {
    icon = "✅";
    title = "VERIFICADO";
  }

  const alertLevel = (etiqueta === "fraudulento") ? (incertidumbre ? "medio" : "alto") : (incertidumbre ? "medio" : "bajo");
  alert.className = `msg-alert alert-${alertLevel}`;

  const iconEl = document.createElement("span");
  iconEl.className = "alert-icon";
  iconEl.textContent = icon;
  header.appendChild(iconEl);

  const titleEl = document.createElement("span");
  titleEl.textContent = `${title} · Riesgo ${alertLevel.toUpperCase()}`;
  header.appendChild(titleEl);
  alert.appendChild(header);

  if (senales.length > 0) {
    const signalsList = document.createElement("ul");
    signalsList.className = "alert-signals";
    for (const s of senales) {
      const li = document.createElement("li");
      li.textContent = s.titulo || s.codigo;
      signalsList.appendChild(li);
    }
    alert.appendChild(signalsList);
  }

  if (recomendaciones.length > 0 && (etiqueta === "fraudulento" || incertidumbre)) {
    const recsTitle = document.createElement("div");
    recsTitle.className = "alert-recs-title";
    recsTitle.textContent = "Recomendaciones:";
    alert.appendChild(recsTitle);

    const recsList = document.createElement("ul");
    recsList.className = "alert-recs";
    for (const r of recomendaciones) {
      const li = document.createElement("li");
      li.textContent = r;
      recsList.appendChild(li);
    }
    alert.appendChild(recsList);
  }

  return alert;
}

function renderAllMessages() {
  chatArea.replaceChildren();
  const msgs = conversations[currentPeer] || [];
  for (const msg of msgs) {
    const isSent = msg.remitente === myPhone;
    renderBubble(msg, isSent);
  }
  scrollToBottom();
}

function appendSystemMessage(text) {
  const el = document.createElement("div");
  el.className = "msg-system";
  el.textContent = text;
  chatArea.appendChild(el);
  scrollToBottom();
}


/* ---- Renderizado de la barra lateral ---- */

function renderContacts() {
  contactsList.replaceChildren();
  const peers = Object.keys(conversations);
  if (peers.length === 0) {
    const li = document.createElement("li");
    li.className = "no-contacts";
    li.textContent = "Aún no hay conversaciones.";
    contactsList.appendChild(li);
    return;
  }
  for (const peer of peers) {
    const msgs = conversations[peer];
    const last = msgs[msgs.length - 1];

    const li = document.createElement("li");
    li.className = "contact-item" + (peer === currentPeer ? " active" : "");
    li.addEventListener("click", () => openChat(peer));

    const dot = document.createElement("span");
    dot.className = `contact-dot ${onlineUsers.includes(peer) ? "online" : "offline"}`;
    li.appendChild(dot);

    const info = document.createElement("div");
    const numEl = document.createElement("span");
    numEl.className = "contact-number";
    numEl.textContent = peer;
    info.appendChild(numEl);

    if (last) {
      const prev = document.createElement("span");
      prev.className = "contact-preview";
      const prefix = last.remitente === myPhone ? "Tú: " : "";
      prev.textContent = prefix + (last.texto || "").substring(0, 40);
      info.appendChild(prev);
    }
    li.appendChild(info);
    contactsList.appendChild(li);
  }
}

function renderOnline() {
  onlineList.replaceChildren();
  const others = onlineUsers.filter(u => u !== myPhone);
  if (others.length === 0) {
    const li = document.createElement("li");
    li.className = "no-online";
    li.textContent = "Ningún otro usuario conectado.";
    onlineList.appendChild(li);
    return;
  }
  for (const user of others) {
    const li = document.createElement("li");
    li.className = "online-item";
    li.addEventListener("click", () => openChat(user));

    const dot = document.createElement("span");
    dot.className = "online-dot";
    li.appendChild(dot);

    const name = document.createElement("span");
    name.className = "online-name";
    name.textContent = user;
    li.appendChild(name);

    onlineList.appendChild(li);
  }
}

function updateOnline(users) {
  onlineUsers = users;
  renderOnline();
  renderContacts();
}

function setPeerOnline(isOnline) {
  peerStatus.textContent = isOnline ? "En línea" : "Desconectado";
  peerStatus.className = `peer-status ${isOnline ? "online" : "offline"}`;
}


/* ---- Abrir una conversación ---- */

function openChat(peer) {
  currentPeer = peer;
  peerPhone.textContent = peer;
  setPeerOnline(onlineUsers.includes(peer));
  noChat.hidden = true;
  activeChat.hidden = false;

  // Mobile: hide sidebar, show chat
  sidebar.classList.add("sidebar-hidden");
  chatMain.classList.remove("main-hidden");

  // Solicitar historial al servidor
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ tipo: "historial", destinatario: peer }));
  }

  renderAllMessages();
  renderContacts();
  msgInput.focus();
}


/* ---- Event Listeners ---- */

// Login
loginForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const phone = cleanPhone(myPhoneInput.value);
  if (!phone) return;
  connect(phone);
});

function showLoginError(msg) {
  loginError.textContent = msg;
  loginError.hidden = false;
  loginScreen.hidden = false;
  chatScreen.hidden = true;
}

// Logout
logoutBtn.addEventListener("click", disconnect);

// Nueva conversación
newChatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const peer = cleanPhone(destPhoneInput.value);
  if (!peer || peer === myPhone) return;
  destPhoneInput.value = "";
  if (!conversations[peer]) conversations[peer] = [];
  openChat(peer);
});

// Enviar mensaje
sendForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = msgInput.value.trim();
  if (!text || !currentPeer || !ws || ws.readyState !== WebSocket.OPEN) return;

  ws.send(JSON.stringify({
    tipo: "mensaje",
    destinatario: currentPeer,
    texto: text,
  }));
  msgInput.value = "";
  msgInput.focus();
});

// Botón volver (mobile)
backBtn.addEventListener("click", () => {
  sidebar.classList.remove("sidebar-hidden");
  chatMain.classList.add("main-hidden");
  currentPeer = "";
  renderContacts();
});

// Mantener conexión viva
setInterval(() => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ tipo: "ping" }));
  }
}, 25000);

