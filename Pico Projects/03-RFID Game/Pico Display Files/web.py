import network, socket, time
try:
    import ntptime
except ImportError:
    ntptime = None

def connect_wifi(ssid, password, timeout_s=15):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(ssid, password)
    start = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), start) > timeout_s * 1000:
            return None
        time.sleep_ms(200)
    if ntptime:
        try:
            ntptime.settime()
        except Exception:
            pass  # game still works fine without accurate timestamps
    return wlan.ifconfig()[0]

def start_server(port=80):
    addr = socket.getaddrinfo("0.0.0.0", port)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(2)
    s.setblocking(False)
    return s

def poll_server(server, render_fn):
    """Call every loop iteration. Does nothing if no one is connecting."""
    try:
        client, _ = server.accept()
    except OSError:
        return
    try:
        client.settimeout(1.0)
        client.recv(1024)  # we don't parse the request - every hit gets the same page
        body = render_fn()
        client.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n" + body)
    except Exception:
        pass
    finally:
        client.close()