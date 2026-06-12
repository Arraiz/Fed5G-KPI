# Vankom LMT API – GET/POST Reference

Referencia práctica de endpoints Vankom usados en este proyecto, con parámetros y formato de request/response.

## Base URL

- Ejemplo: `http://192.168.25.50`

## Autenticación (obligatoria, en orden)

Todas las llamadas funcionales requieren sesión autenticada.

### 1) Obtener captcha token

- **Method:** `GET`
- **Path:** `/api/captcha`
- **Query params:** ninguno
- **Body:** ninguno
- **Cookies requeridas:** ninguna
- **Devuelve:** `CaptchaToken` (cookie y/o en `Data`)

### 2) Verificar captcha

- **Method:** `GET`
- **Path:** `/api/captcha/verify`
- **Query params:**
  - `code` (string), ejemplo `1111`
- **Body:** ninguno
- **Cookies requeridas:**
  - `CaptchaToken` (del paso 1)
- **Devuelve:** `CaptchaToken` actualizado

### 3) Login

- **Method:** `POST`
- **Path:** `/api/login`
- **Query params:** ninguno
- **Body JSON:**

```json
{
  "Name": "admin",
  "Password": "lmt_2023"
}
```

- **Cookies requeridas:**
  - `CaptchaToken` (del paso 2)
- **Devuelve:** `AuthToken`

### Cookies requeridas para el resto

- `CaptchaToken`
- `AuthToken`

---

## Endpoints GET

### `GET /api/cn/online-users`

- **Query params:** ninguno
- **Body:** ninguno
- **Uso:** lista de UEs online
- **Campos típicos en `Data[]`:**
  - `Imsi`, `Ipv4`, `Mask`, `Status`, `UserLabel`, `LinkQuality`
  - `Sinr`, `Rsrp`, `Dlmbr`, `Ulmbr`
  - `TransmissionDelay`, `DelayChange`, `PacketLossProbability`, `ChannelLoadCondition`

### `GET /api/alarm/list`

- **Query params:** ninguno
- **Body:** ninguno
- **Uso:** alarmas en tiempo real
- **Notas:** puede devolver `Data: null` si no hay alarmas activas

### `GET /api/alarm/list-history`

- **Query params:** ninguno
- **Body:** ninguno
- **Uso:** histórico de alarmas
- **Campos típicos en `Data[]`:**
  - `FaultId`, `FaultSource`, `FaultSeverity`
  - `AlarmRaisedTime`, `AlarmClearedTime`
  - `SerialNumber`, `AlarmIdentifier`
  - `EventType`, `ProbableCause`, `SpecificProblem`, `AdditionalInformation`

### `GET /api/param/value`

- **Query params:**
  - `xpath` (string, obligatorio)
- **Body:** ninguno
- **Uso:** leer valor puntual de parámetro de configuración
- **Ejemplo:**
  - `/duoam:InternetGatewayDevice/Services/FAPService[name='3333']/CellConfig/FIVEGNR/RAN/CommonInfo/NRModeInfo/NRArfcnDL`

### `GET /api/param/status-info`

- **Query params:**
  - `xpath` (string, obligatorio)
- **Body:** ninguno
- **Uso:** leer estado de celda/objeto
- **Ejemplo:**
  - `/oam:Device/Services/FAPService[name='3333']/CellState/BBU`
- **Valor de estado celda (`Data[].Value`):**
  - `1`: activated
  - `2`: configured, not activated
  - `8`: deleted
  - `16`: activation in progress

---

## Endpoints POST

### `POST /api/login`

- Ya descrito en autenticación.

### `POST /api/param/set-parameters`

- **Query params:** ninguno
- **Body JSON:** objeto key/value donde la key es xpath y value el nuevo valor

```json
{
  "/oam:Device/LogMgmt/OAMLogLevel": "3"
}
```

- **Uso:** escritura de parámetros
- **Estado en este proyecto:** **no usado** en scraper (modo read-only)

### `POST /api/param/set-parameters` (alta de IMSI)

- Mismo endpoint
- **Body JSON ejemplo:**

```json
{
  "/nrgc:NRGC/UDM/supi_list[supi='460060000000001']": "460060000000001",
  "/nrgc:NRGC/UDM/supi_list[supi='460060000000001']/user_label": "custom_name"
}
```

- **Uso:** provisión de usuario
- **Estado en este proyecto:** **no usado** (solo lectura)

---

## Envelope de respuesta

Formato común:

```json
{
  "Code": "200",
  "Message": "Success",
  "Data": "..."
}
```

- `Code == "200"`: éxito
- cualquier otro `Code`: error lógico de API

---

## Comportamiento observado en tu gNB (test real)

Probado contra `http://192.168.25.50`:

- `/api/captcha` -> OK
- `/api/captcha/verify?code=1111` -> `Code=500`, `Message=Captcha Error`
- `/api/login` -> `Code=200` igualmente
- endpoints de lectura (`online-users`, `alarm/list`, `alarm/list-history`) -> responden OK tras login

Conclusión: en este equipo conviene tolerar fallo de `captcha/verify` y continuar al login.
