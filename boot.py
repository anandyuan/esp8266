import network
import time
import socket
import machine
import ntptime
import json
import uasyncio as asyncio

# 配置
WIFI_SSID = "21"
WIFI_PASSWORD = "12345678"
AP_SSID = "8266"
AP_PASSWORD = "12345678"
NTP_SERVER = "ntp.ntsc.ac.cn"
HTTP_PORT = 80

# GPIO配置
gpio2 = machine.Pin(2, machine.Pin.OUT)
gpio4 = machine.Pin(4, machine.Pin.OUT)
gpio5 = machine.Pin(5, machine.Pin.OUT)
gpio12 = machine.Pin(12, machine.Pin.OUT)
gpio13 = machine.Pin(13, machine.Pin.OUT)
gpio14 = machine.Pin(14, machine.Pin.OUT)
pwm5 = machine.PWM(gpio5)

# 全局变量
wlan = network.WLAN(network.STA_IF)
ap = network.WLAN(network.AP_IF)
start_time = time.time()
ap_mode = False
gpio_states = {
    2: 0,
    4: 0,
    12: 0,
    13: 0,
    14: 0
}
gpio_timings = {}
gpio_delays = {}

# LED闪烁函数


async def blink_led(pin, interval):
    while True:
        pin.value(0)  # 低电平点亮
        await asyncio.sleep_ms(interval)
        pin.value(1)  # 高电平熄灭
        await asyncio.sleep_ms(interval)

# 连接WIFI


async def connect_wifi():
    global wlan
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    blink_task = asyncio.create_task(blink_led(gpio2, 100))
    for _ in range(150):  # 15s
        if wlan.isconnected():
            blink_task.cancel()
            gpio2.value(0)
            await asyncio.sleep(3)
            gpio2.value(1)
            print("WIFI connected:", wlan.ifconfig())
            return True
        await asyncio.sleep_ms(100)
    blink_task.cancel()
    return False

# 开启AP模式


async def start_ap():
    global ap, ap_mode
    ap.active(True)
    ap.config(essid=AP_SSID, password=AP_PASSWORD,
              authmode=network.AUTH_WPA_WPA2_PSK)
    ap_mode = True
    print("AP started:", ap.ifconfig())
    blink_task = asyncio.create_task(blink_led(gpio2, 500))
    await asyncio.sleep(3)
    blink_task.cancel()
    gpio2.value(1)

# 同步时间


def sync_time():
    for _ in range(3):
        try:
            ntptime.settime()
            s = time.localtime()
            print(
                f"Time synchronized from NTP\nNow Time:{s[0]}-{s[1]}-{s[2]} {s[3]}:{s[4]}")
            return True
        except Exception as e:
            print(f"NTP sync failed: {e}")
            time.sleep(1)
    return False

# HTTP请求处理


async def handle_request(reader, writer):
    global gpio_states, gpio_timings, gpio_delays
    try:
        request_line = await reader.readline()
        request = request_line.decode().strip()
        print(f"Request: {request}")

        if request:
            path = request.split(" ")[1]
            if path.startswith("/?localtime="):
                try:
                    localtime = int(path.split("=")[1])
                    rtc = machine.RTC()
                    rtc.datetime(time.gmtime(localtime))
                    response = json.dumps(
                        {"status": "ok", "message": "Time synchronized"})
                except:
                    response = json.dumps(
                        {"status": "error", "message": "Invalid timestamp"})

            elif path.startswith("/gpio"):
                try:
                    gpio_num = int(path.split("gpio")[1].split("?")[0])
                    if gpio_num in [2, 4, 12, 13, 14]:
                        if "state" in path:
                            state = int(path.split("state=")[1])
                            gpio_states[gpio_num] = state
                            machine.Pin(gpio_num, machine.Pin.OUT).value(state)
                            response = json.dumps(
                                {"status": "ok", "gpio": gpio_num, "state": state})
                        elif "pwm" in path and gpio_num == 5:
                            pwm_value = int(path.split("pwm=")[1])
                            pwm5.duty(pwm_value)
                            response = json.dumps(
                                {"status": "ok", "gpio": gpio_num, "pwm": pwm_value})
                        elif "timing" in path:
                            timing = int(path.split("timing=")[1])
                            gpio_timings[gpio_num] = time.time() + timing
                            response = json.dumps(
                                {"status": "ok", "gpio": gpio_num, "timing": timing})
                        elif "delay" in path:
                            delay = int(path.split("delay=")[1])
                            if delay > time.time():
                                gpio_delays[gpio_num] = delay
                                response = json.dumps(
                                    {"status": "ok", "gpio": gpio_num, "delay": delay})
                            else:
                                response = json.dumps(
                                    {"status": "error", "message": "Delay time is in the past"})
                        else:
                            response = json.dumps(
                                {"status": "error", "message": "Invalid parameters"})
                    else:
                        response = json.dumps(
                            {"status": "error", "message": "Invalid GPIO number"})
                except (ValueError, IndexError):
                    response = json.dumps(
                        {"status": "error", "message": "Invalid request"})
            else:
                response = json.dumps(
                    {"status": "error", "message": "Invalid path"})

            # 确保响应体不为空并正确发送
            print("Response:", response)

            # 发送 HTTP 响应头和响应体
            response_header = (
                'HTTP/1.1 200 OK\r\n'
                'Content-Type: application/json\r\n'
                'Access-Control-Allow-Origin: *\r\n'
                'Content-Length: {}\r\n'.format(len(response)) +
                '\r\n'  # 空行，标识响应头与响应体分隔
            )

            # 合并响应头和响应体
            writer.write(response_header.encode() + response.encode())

            # 等待数据发送完毕
            await writer.drain()

            # 手动关闭连接
            await writer.wait_closed()

    except OSError as e:
        print("Client disconnected:", e)


async def main():
    if await connect_wifi():
        sync_time()
    else:
        await start_ap()

    async def check_timings():
        while True:
            now = time.time()
            for gpio, target_time in list(gpio_timings.items()):
                if now >= target_time:
                    gpio_states[gpio] = 1 - gpio_states[gpio]  # 翻转状态
                    machine.Pin(gpio, machine.Pin.OUT).value(gpio_states[gpio])
                    del gpio_timings[gpio]
            for gpio, target_time in list(gpio_delays.items()):
                if now >= target_time:
                    gpio_states[gpio] = 1 - gpio_states[gpio]  # 翻转状态
                    machine.Pin(gpio, machine.Pin.OUT).value(gpio_states[gpio])
                    del gpio_delays[gpio]
            await asyncio.sleep(1)

    # 启动HTTP服务器
    async def request_handler(reader, writer):
        await handle_request(reader, writer)

    # 创建TCP服务器并开始监听
    server = await asyncio.start_server(request_handler, '0.0.0.0', HTTP_PORT)
    print("HTTP server started")

    # 在后台运行检查定时任务
    asyncio.create_task(check_timings())

    # 手动管理循环
    while True:
        await asyncio.sleep(1)

try:
    asyncio.run(main())
except (KeyboardInterrupt, SystemExit):
    print("Exiting...")
finally:
    asyncio.new_event_loop()  # 清理事件循环
