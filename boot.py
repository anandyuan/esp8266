import network
import time
import ntptime
import ujson
from machine import PWM, Pin
import socket

# Define your WiFi credentials
WIFI_SSID = "21"
WIFI_PASSWORD = "12345678"

# Define your AP credentials
AP_SSID = "8266"
AP_PASSWORD = "12345678"

# GPIO2定义为LED
led = Pin(2, Pin.OUT)
led_pwm = PWM(led, freq=500)
gpio_pins = {
    4: Pin(4, Pin.OUT),
    5: Pin(5, Pin.OUT),
    12: Pin(12, Pin.OUT),
    13: Pin(13, Pin.OUT),
    14: Pin(14, Pin.OUT),
}
gpio_pwm = {5: PWM(gpio_pins[5], freq=500)}  # 仅GPIO5支持PWM

# 存储定时任务的定时器列表
timers = []

# NTP同步时区设置（单位：秒，+8小时 = 8 * 60 * 60）
TIMEZONE_OFFSET = 8 * 60 * 60


# 处理GPIO通用功能
def handle_gpio_request(gpio_pin, params, pwm_obj=None):
    if "state" in params:
        if params["state"]:  # 设置高低电平
            value = int(params["state"])
            gpio_pin.value(value)
            return {"status": "success", "state": value}
        else:  # 获取当前高低电平状态
            state = gpio_pin.value()
            return {"status": "success", "state": state}
    elif "pwm" in params and pwm_obj:
        if params["pwm"]:  # 设置PWM占空比
            duty = int(params["pwm"])
            duty = max(0, min(1023, duty))
            pwm_obj.duty(duty)
            return {"status": "success", "pwm": duty}
        else:  # 获取PWM占空比
            duty = pwm_obj.duty()
            return {"status": "success", "pwm": duty}
    elif "timing" in params:  # 定时翻转
        delay = int(params["timing"])
        if delay <= 0:
            return {"status": "error", "message": "Timing must be greater than 0"}

        # 设置硬件定时器
        timer = machine.Timer(-1)  # 创建临时定时器
        timers.append(timer)  # 存储定时器，防止被垃圾回收
        timer.init(
            period=delay * 1000,
            mode=machine.Timer.ONE_SHOT,
            callback=lambda t: flip_gpio(gpio_pin, timer),
        )
        return {"status": "success", "timing": delay}
    elif "delay" in params:  # 延时翻转到指定时间
        timestamp = int(params["delay"])
        current_time = int(time.time())
        if timestamp <= current_time:
            return {"status": "error", "message": "Timestamp must be in the future"}

        delay = timestamp - current_time
        # 设置硬件定时器
        timer = machine.Timer(-1)  # 创建临时定时器
        timers.append(timer)  # 存储定时器
        timer.init(
            period=delay * 1000,
            mode=machine.Timer.ONE_SHOT,
            callback=lambda t: flip_gpio(gpio_pin, timer),
        )
        return {"status": "success", "delay": timestamp}
    else:
        return {"status": "error", "message": "Invalid parameters"}


# 翻转GPIO状态
def flip_gpio(gpio_pin, timer):
    gpio_pin.value(1 - gpio_pin.value())  # 翻转电平
    timers.remove(timer)  # 从定时器列表中移除
    timer.deinit()  # 关闭定时器
    print(f"GPIO {gpio_pin} flipped")


# 设置本地时间
def set_local_time(timestamp):
    rtc = machine.RTC()
    tm = time.localtime(timestamp)
    rtc.datetime((tm[0], tm[1], tm[2], tm[6], tm[3], tm[4], tm[5], 0))  # 设置RTC时间
    print("Local time set to:", time.strftime("%Y-%m-%d %H:%M:%S", tm))


# API处理
def handle_request(conn, request):
    try:
        # print("Request received:", request)
        if " " not in request:
            raise ValueError("Invalid request format")

        parts = request.split(" ", 2)
        if len(parts) < 2:
            raise ValueError("Invalid request format")

        path_query = parts[1]
        if "?" in path_query:
            path, query = path_query.split("?", 1)
            params = dict(x.split("=") for x in query.split("&") if "=" in x)
        else:
            path, params = path_query, {}



        # GPIO2处理
        if path == "/gpio2":
            result = handle_gpio_request(led, params, pwm_obj=led_pwm)
            send_response(conn, 200, result)

        # GPIO4处理
        elif path == "/gpio4":
            result = handle_gpio_request(gpio_pins[4], params)
            send_response(conn, 200, result)

        # GPIO5处理
        elif path == "/gpio5":
            result = handle_gpio_request(gpio_pins[5], params, pwm_obj=gpio_pwm[5])
            send_response(conn, 200, result)

        # GPIO12处理
        elif path == "/gpio12":
            result = handle_gpio_request(gpio_pins[12], params)
            send_response(conn, 200, result)

        # GPIO13处理
        elif path == "/gpio13":
            result = handle_gpio_request(gpio_pins[13], params)
            send_response(conn, 200, result)

        # GPIO14处理
        elif path == "/gpio14":
            result = handle_gpio_request(gpio_pins[14], params)
            send_response(conn, 200, result)

                # 处理 /?localtime 接口
        elif path == "/" and "localtime" in params:
            timestamp = int(params["localtime"])
            if timestamp > 0:  # 验证时间戳
                set_local_time(timestamp)
                response = {
                    "status": "success",
                    "localtime": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(timestamp)
                    ),
                }
            else:
                response = {"status": "error", "message": "Invalid path or parameters"}

            # 发送HTTP响应
            send_response(conn, 200, response)
        # 无效路径处理
        else:
            send_response(conn, 404, {"status": "error", "message": "Invalid path"})
    except Exception as e:
        print("Error handling request:", e)
        send_response(conn, 500, {"status": "error", "message": str(e)})
    finally:
        conn.close()


# LED PWM控制
def set_led_brightness(duty):
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


# 从NTP服务器同步时间
def sync_time():
    retries = 3
    while retries > 0:
        try:
            print("Synchronizing time with NTP server...")
            ntp.host = "ntp.ntsc.ac.cn"  # 设置NTP服务器
            ntptime.settime()  # 从NTP服务器获取UTC时间
            now = time.time() + TIMEZONE_OFFSET  # 手动调整时区
            tm = time.localtime(now)
            rtc = machine.RTC()
            rtc.datetime(
                (tm[0], tm[1], tm[2], tm[6], tm[3], tm[4], tm[5], 0)
            )  # 设置本地RTC时间
            print("Time synchronized:", time.strftime("%Y-%m-%d %H:%M:%S", tm))
            return True
        except Exception as e:
            print("Failed to synchronize time. Retrying... ({})".format(retries))
            retries -= 1
            time.sleep(2)
    print("NTP time synchronization failed!")
    return False


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
            time.sleep(3)
            led.on()
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


# 主函数
def main():
    global timers
    timers = []  # 清空定时器列表
    ap = network.WLAN(network.AP_IF)

    wlan = connect_wifi()
    if wlan and wlan.isconnected():
        print("Device is in WiFi mode.")
        ap.active(False)
        sync_time()
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
