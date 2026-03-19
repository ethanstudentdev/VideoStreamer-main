#This code will run on the client
import socket

# Create a TCP/IP client outbound socket
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# Connects the socket to the server's address and port 
# (CHANGE IP ADDRESS TO YOUR SERVER'S IP IF NOT RUNNING LOCALLY)
client.connect(('192.168.50.98', 5000))

# Test sending a message to the server
client.send('Hello, Server!'.encode())
print(client.recv(1024).decode())