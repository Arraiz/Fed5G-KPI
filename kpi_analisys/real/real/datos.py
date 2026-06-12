import pandas as pd
import numpy as np
import datetime

np.random.seed(42)
start = datetime.datetime(2025, 11, 7, 10, 0, 0)
minutes = 60 * 12  # 12 horas de datos

# Fija una semilla aleatoria (seed) para que los resultados sean reproducibles.
# Define un inicio de simulación (10:00 AM).
# Genera datos para 12 horas (720 minutos).

sites = ['madrid_centro', 'valencia_fp']
cells = ['cell_01', 'cell_02', 'cell_03']
users = [f'UE_{i:03d}' for i in range(1, 31)]
slices = ['eMBB', 'URLLC', 'IoT']

# Simula dos sedes (Madrid y Valencia).
# Cada sede tiene 3 celdas (antenas).
# Cada celda atiende usuarios (UE) numerados del 1 al 30.

# Tres slices 5G:
    # eMBB: Enhanced Mobile Broadband (alta velocidad).
    # URLLC: Ultra Reliable Low Latency (baja latencia, alta fiabilidad).
    # IoT: Internet of Things (bajo ancho de banda, muchos dispositivos).

data = []

for minute in range(minutes):
    timestamp = start + datetime.timedelta(minutes=minute)
    for cell in cells:
        slice_id = np.random.choice(slices, p=[0.6, 0.2, 0.2])
        for user in np.random.choice(users, size=10, replace=False):
                sinr = np.random.normal(20, 5)
                prb_util = np.clip(np.random.normal(60, 20), 0, 100)
                throughput_dl = max(0, np.random.normal(100 - (100 - prb_util)/2, 15))
                throughput_ul = max(0, throughput_dl * np.random.uniform(0.2, 0.4))
                latency = np.random.normal(10 + prb_util/20, 3)
                jitter = np.random.normal(latency/10, 1)
                pkt_loss = abs(np.random.normal(0.2 + (100 - sinr)/200, 0.1))
            
                data.append({
                    'time': timestamp,
                    'cell_id': cell,
                    'user_id': user,
                    'slice_id': slice_id,
                    'throughput_dl_mbps': throughput_dl,
                    'throughput_ul_mbps': throughput_ul,
                    'latency_ms': latency,
                    'jitter_ms': jitter,
                    'packet_loss_pct': pkt_loss,
                })

df = pd.DataFrame(data)
df.to_csv("synthetic_5g_kpis.csv", index=False)

# Por cada minuto → cada sede → cada celda → elige un tipo de servicio (“slice”) con más probabilidad de ser eMBB (60%).
# Luego selecciona 10 usuarios activos aleatorios en ese minuto.