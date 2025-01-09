import network
import time
import ujson
from machine import PWM, Pin
import socket

# GPIO定义
LED_PIN = 2
GPIO4 = 4
GPIO5 = 5
GPIO12 = 12
GPIO13 = 13
GPIO14 = 14

# WiFi配置
WIFI_SSID = "ChinaNet-gtzk"
WIFI_PASSWORD = "11111111"
AP_SSID = "8266"
AP_PASSWORD = "12345678"

# 全局变量
led = Pin(LED_PIN, Pin.OUT)
led_pwm = None  # 用于PWM控制的对象
gpio_pwm = {GPIO5: None}
gpio_pins = {
    GPIO4: Pin(GPIO4, Pin.OUT),
    GPIO5: Pin(GPIO5, Pin.OUT),
    GPIO12: Pin(GPIO12, Pin.OUT),
    GPIO13: Pin(GPIO13, Pin.OUT),
    GPIO14: Pin(GPIO14, Pin.OUT),
}

# LED初始化
def init_led_pwm():
    global led_pwm
    led_pwm = PWM(led, freq=1000, duty=0)

# LED PWM控制
def set_led_brightness(duty):
    global led_pwm
    if not led_pwm:
        init_led_pwm()
    led_pwm.duty(duty)

# LED闪烁
def led_blink(delay, duration):
    start_time = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start_time) < duration:
        led.off()  # 低电平点亮
        time.sleep_ms(delay)
        led.on()  # 高电平熄灭
        time.sleep_ms(delay)
    led.on()  # 保持熄灭状态

# WiFi连接
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    print("Attempting to connect to WiFi...")

    led.on()
    # 尝试15秒连接WiFi，并100ms闪烁一次LED
    for _ in range(150):
        if wlan.isconnected():
            print("WiFi connected! IP:", wlan.ifconfig()[0])
            led.off()
            return wlan
        time.sleep_ms(100)
        led.value(not led.value())

        

    
    print("Failed to connect to WiFi.")
    return None

# 开启AP模式
def start_ap_mode():
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=AP_SSID, password=AP_PASSWORD)
    print("AP Mode started. SSID:", AP_SSID, "Password:", AP_PASSWORD)
    led_blink(500, 10000)  # 500ms闪烁10秒
    led.on()
    return ap

# HTTP响应
def send_response(conn, status_code, content):
    conn.send(f"HTTP/1.1 {status_code} OK\r\n")
    conn.send("Content-Type: application/json\r\n")
    conn.send("Connection: close\r\n\r\n")
    conn.send(ujson.dumps(content))
    conn.close()

# API处理
def handle_request(conn, request):
    try:
        # print("Request received:", request)
        if "?" in request:
            path, query = request.split(" ", 2)[1].split("?")
        else:
            path, query = request.split(" ", 2)[1], ""
        params = dict(x.split("=") for x in query.split("&") if "=" in x)

        if path == "/gpio2":
            if "pwm" in params:
                duty = int(params["pwm"])
                duty = max(0, min(1023, duty))  # 限制duty在0-1023范围内
                set_led_brightness(duty)
                send_response(conn, 200, {"status": "success", "pwm": duty})
            else:
                send_response(conn, 400, {"status": "error", "message": "Missing 'pwm' parameter"})
        else:
            send_response(conn, 404, {"status": "error", "message": "Invalid path"})
    except Exception as e:
        print("Error handling request:", e)
        send_response(conn, 500, {"status": "error", "message": str(e)})

# 主函数
def main():
    ap = network.WLAN(network.AP_IF)
    
    wlan = connect_wifi()
    if wlan and wlan.isconnected():
        print("Device is in WiFi mode.")
        ap.active(False)
    else:
        start_ap_mode()

    print("Starting HTTP Server...")
    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    s = socket.socket()
    s.bind(addr)
    s.listen(5)
    print("Listening on:", addr)

    while True:
        conn, addr = s.accept()
        print("Client connected from:", addr)
        request = conn.recv(1024).decode("utf-8")
        handle_request(conn, request)

if __name__ == "__main__":
    main()
