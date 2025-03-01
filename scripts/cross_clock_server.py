import http.server
import socketserver
import socket
import threading
import urllib.parse

SERVER_IP = "0.0.0.0"
UDP_PORT = 2008
HTTP_PORT = 2009

class MyUDPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data = self.request[0].strip()
        socket = self.request[1]
        print(f"Message from {self.client_address}: {data.decode()}")
        self.server.client_addresses.add(self.client_address)

class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        params = urllib.parse.parse_qs(post_data.decode())
        message = params.get('message', [''])[0]
        message += "\n"
        self.server.udp_server.send_message_to_all_clients(message)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Message sent")

class MyUDPServer(socketserver.UDPServer):
    allow_reuse_address = True
    client_addresses = set()

    def send_message_to_all_clients(self, message):
        for client_address in self.client_addresses:
            self.socket.sendto(message.encode("UTF-8"), client_address)

class MyHTTPServer(socketserver.TCPServer):
    allow_reuse_address = True

def run_udp_server(server_class, handler_class):
    server = server_class((SERVER_IP, UDP_PORT), handler_class)
    print(f"UDP server started at {SERVER_IP}:{UDP_PORT}")
    return server

def run_http_server(server_class, handler_class, udp_server):
    httpd = server_class((SERVER_IP, HTTP_PORT), handler_class)
    httpd.udp_server = udp_server
    print(f"HTTP server started at {SERVER_IP}:{HTTP_PORT}")
    httpd.serve_forever()

if __name__ == "__main__":
    udp_server = run_udp_server(MyUDPServer, MyUDPHandler)
    udp_thread = threading.Thread(target=udp_server.serve_forever)
    udp_thread.start()

    run_http_server(MyHTTPServer, MyHTTPRequestHandler, udp_server)
