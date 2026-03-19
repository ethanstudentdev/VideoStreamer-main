#This code will run on the server
import socket

# Create a TCP/IP server inbound socket
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# Binds the socket to the server's address and port
server.bind(('0.0.0.0', 5000))

# Listen for incoming connections Queue or ignore after 5 connections
server.listen(5)

while True:
    # Send message if a connection is made
    connection, address = server.accept()
    print(connection.recv(1024).decode())
    connection.send('Hello from the Server!'.encode())
