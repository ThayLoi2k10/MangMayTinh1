from protocol import Packet, MSG_AUTH_REQ, encode_packet, decode_packet, dump_json, load_json

# Tạo gói tin thử nghiệm
data = dump_json({"username": "alice", "udp_port": 9005})
pkt_send = Packet(msg_type=MSG_AUTH_REQ, seq_no=1, payload=data)

# Đóng gói và giải mã
raw_bytes = encode_packet(pkt_send)
pkt_recv = decode_packet(raw_bytes)

print(f"Header size + Payload: {len(raw_bytes)} bytes")
print(f"Message Type: {hex(pkt_recv.msg_type)}")
print(f"Status Code: {pkt_recv.status}")
print(f"Sequence No: {pkt_recv.seq_no}")
print(f"Payload Data: {load_json(pkt_recv.payload)}")