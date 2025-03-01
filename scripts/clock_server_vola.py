from flask import Flask, request, jsonify
import socket
import threading
import sqlite3
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app)
current_working_directory = os.getcwd()
print(current_working_directory)

# Constants
DB_PATH = "/home/administrator/aassk/new_system/site.db"

with sqlite3.connect(DB_PATH) as con:
    cur = con.cursor()
    listen_ip = cur.execute("SELECT params FROM microservices WHERE path = 'clock_server_vola.py';").fetchone()[0]

# TCP Server settings
tcp_host = listen_ip
tcp_port = 7000
connected_clients = []


def tcp_server():
    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((tcp_host, tcp_port))
        server_socket.listen(5)
        print(f"TCP server listening on {tcp_host}:{tcp_port}")

        while True:
            try:
                connection, client_address = server_socket.accept()
                print(f"TCP client connected: {client_address}")
                connected_clients.append(connection)
            except Exception as e:
                print(f"Error accepting connections: {e}")
                continue
    except Exception as e:
        print(f"Failed to start TCP server: {e}")

def send_timestamp_to_clients(timestamp):
    data = f"TN_{timestamp}\r\n".encode('utf-8')
    print(data)
    for client in connected_clients[:]:  # Iterate over a shallow copy of the list
        try:
            client.sendall(data)
            print(f"Sent timestamp to {client.getpeername()}")
        except Exception as e:
            print(f"Error sending to client: {e}")
            try:
                client.close()
            except Exception as close_e:
                print(f"Error closing client socket: {close_e}")
            connected_clients.remove(client)

@app.route('/send-timestamp', methods=['POST', 'OPTIONS'])
def send_timestamp():
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Content-Type',
        }
        return '', 200, headers
    content = request.json
    timestamp = content['timestamp']
    send_timestamp_to_clients(timestamp)
    return jsonify({"message": "Timestamp sent to TCP clients."})

if __name__ == "__main__":
    # Start the TCP server in a separate thread
    threading.Thread(target=tcp_server, daemon=True).start()

    # Start the Flask API server
    app.run(host='0.0.0.0', port=5000)