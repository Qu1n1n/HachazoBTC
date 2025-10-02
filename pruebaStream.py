import streamlit as st
import pandas as pd
import requests
import websocket
import threading
import json
import plotly.graph_objects as go
from datetime import datetime
import numpy as np
import time

symbol = "BTCUSDT"
depth_lock = threading.Lock()

# === Funciones ===
def cargar_snapshot():
    url = "https://api.binance.com/api/v3/depth"
    params = {"symbol": symbol, "limit": 5000}
    try:
        data = requests.get(url, params=params, timeout=5).json()
        bids = pd.DataFrame(data["bids"], columns=["price", "quantity"], dtype=float)
        asks = pd.DataFrame(data["asks"], columns=["price", "quantity"], dtype=float)
        bids["side"] = "bid"
        asks["side"] = "ask"
        return pd.concat([bids, asks])
    except Exception as e:
        st.warning(f"No se pudo cargar snapshot: {e}")
        precios = [28000, 28100, 28200, 28300]
        return pd.DataFrame({
            "price": precios*2,
            "quantity": [10,20,15,5,8,12,7,9],
            "side": ["bid"]*4 + ["ask"]*4
        })

def aplicar_update(data):
    updates = []
    for price_str, qty_str in data.get("b", []):
        updates.append({"price": float(price_str), "quantity": float(qty_str), "side": "bid"})
    for price_str, qty_str in data.get("a", []):
        updates.append({"price": float(price_str), "quantity": float(qty_str), "side": "ask"})
    update_df = pd.DataFrame(updates)

    with depth_lock:
        st.session_state["orderbook"] = pd.concat([st.session_state["orderbook"], update_df], ignore_index=True)

def on_message(ws, message):
    aplicar_update(json.loads(message))

def iniciar_ws():
    url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@depth@100ms"
    ws = websocket.WebSocketApp(url, on_message=on_message)
    ws.run_forever()

# === Inicialización ===
if "ws_thread" not in st.session_state:
    st.session_state["orderbook"] = cargar_snapshot()
    ws_thread = threading.Thread(target=iniciar_ws, daemon=True)
    ws_thread.start()
    st.session_state["ws_thread"] = ws_thread
    time.sleep(1)

# === UI ===
st.title("📊 Order Book BTC/USDT en tiempo real (Heatmap)")

# Placeholder para actualizar solo la gráfica y datos
placeholder = st.empty()

# Función para actualizar la gráfica dentro del placeholder
def actualizar_grafica():
    with depth_lock:
        ob = st.session_state["orderbook"].copy()

    niveles_bid = ob[ob['side']=='bid']["price"].nunique()
    niveles_ask = ob[ob['side']=='ask']["price"].nunique()

    with placeholder.container():
        st.write(f"🟢 Niveles recibidos: Bids = {niveles_bid}, Asks = {niveles_ask}, Total = {niveles_bid+niveles_ask}")

        if ob.empty:
            st.warning("Cargando datos del order book...")
            return

        best_bid = ob[ob['side'] == 'bid']['price'].max()
        best_ask = ob[ob['side'] == 'ask']['price'].min()
        if pd.isna(best_bid) or pd.isna(best_ask):
            st.warning("No hay datos válidos aún...")
            return

        mid_price = (best_bid + best_ask) / 2
        step = 10
        ob["price"] = (ob["price"] // step * step).astype(int)

        y_vals = sorted(ob["price"].unique(), reverse=True)
        pivot = ob.pivot_table(index="price", columns="side", values="quantity", aggfunc="sum", fill_value=0)
        pivot = pivot.reindex(y_vals, fill_value=0)

        # Escala logarítmica
        z_values = pivot.values
        z_log = np.log1p(z_values)

        hora_actual = datetime.now().strftime("%H:%M:%S")

        # Porcentaje de niveles ocupados
        total_levels = len(y_vals)
        occupied_levels = np.count_nonzero(z_values.sum(axis=1))
        porcentaje_ocupado = occupied_levels / total_levels * 100
        st.write(f"📈 Porcentaje de niveles ocupados en el rango visible: {porcentaje_ocupado:.2f}%")

        # Heatmap
        fig = go.Figure(
            data=go.Heatmap(
                z=z_log,
                x=pivot.columns,
                y=pivot.index,
                colorscale="YlGnBu",
                colorbar=dict(title="Cantidad (log)"),
                zmin=0,
                zmax=z_log.max()
            )
        )

        # Línea roja del mid-price
        fig.add_hline(
            y=mid_price,
            line=dict(color="red", dash="dash", width=2),
            annotation_text=f"Mid-Price: {mid_price:.2f}",
            annotation_font=dict(color="red", size=12),  # <--- Texto en rojo
            annotation_position="top left"
        )

        # Eje Y dinámico según niveles disponibles
        y_min = pivot.index.min()
        y_max = pivot.index.max()

        fig.update_layout(
            title=f"Heatmap BTC/USDT - Última actualización: {hora_actual}",
            xaxis_title="Side (bid/ask)",
            yaxis_title="Price",
            yaxis=dict(range=[y_min, y_max]),
            height=700
        )

        st.plotly_chart(fig, use_container_width=True)

# Llamada inicial
actualizar_grafica()
