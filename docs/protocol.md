## 1. Overview
TCP_port: 9000
UDP_port: 9001

## 2. Packet Format
Đồng nhất cho cả TCP và UDP, gồm một Header nhị phân cố định **8 bytes**, **Big-Endian**, Payload có độ dài thay đổi.

### 2.1. Bit-level Layout

​```text
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|         Magic Number         |  Msg Type (1B)|  Status (1B)  |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|       Sequence No (2B)       |      Payload Length (2B)      |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       Payload (N bytes)...                    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
​```

### 2.2. Header Fields Specification

| **Tên trường**      | **Kiểu dữ liệu** | **Kích thước** | **Mô tả** |
|---------------------|------------------|----------------|-----------|
| **Magic Number**    | `uint16`         | 2 bytes        | Giá trị cố định `0xDCBA`. Định danh gói tin hợp lệ của hệ thống, giúp lọc dữ liệu rác. |
| **Message Type**    | `uint8`          | 1 byte         | Mã phân loại chức năng của thông điệp (Opcode). |
| **Status Code**     | `uint8`          | 1 byte         | Trả mã trạng thái thực thi: `0x00` (None/Not Applicable), `0x01` (Success / OK), `0x02` (Error / Duplicate). |
| **Sequence Number** | `uint16`         | 2 bytes        | Số thứ tự tăng dần của gói tin, phục vụ theo dõi gói tin và xử lý mất gói trên kênh UDP. Mặc định là `0` trên kênh điều khiển TCP. |
| **Payload Length**  | `uint16`         | 2 bytes        | Độ dài chính xác của phần thân dữ liệu (0 đến 65,535 bytes). |

## 3. Message Types (Opcodes)

| **Opcode** | **Tên thông điệp** | **Kênh** | **Hướng truyền** | **Mô tả** |
|------------|--------------------|----------|------------------|----------|
| `0x01` | `HELLO_REQ` | TCP | Client $\rightarrow$ Server | Khởi tạo bắt tay ứng dụng sau khi thiết lập kết nối TCP. |
| `0x02` | `HELLO_RESP` | TCP | Server $\rightarrow$ Client | Xác nhận sẵn sàng tiếp nhận yêu cầu xác thực. |
| `0x03` | `AUTH_REQ` | TCP | Client $\rightarrow$ Server | Gửi thông tin định danh người dùng và cổng UDP lắng nghe. |
| `0x04` | `AUTH_RESP` | TCP | Server $\rightarrow$ Client | Kết quả xác thực (Thành công kèm Session ID hoặc Thất bại). |
| `0x05` | `LOGOUT_REQ` | TCP | Client $\rightarrow$ Server | Yêu cầu đóng phiên làm việc chủ động (Graceful Disconnect). |
| `0x06` | `LOGOUT_RESP` | TCP | Server $\rightarrow$ Client | Xác nhận phiên đã được xóa thành công trước khi đóng socket. |
| `0x10` | `HEARTBEAT` | UDP | Client $\rightarrow$ Server | Gói tin giữ nhịp định kỳ (mỗi 5s) duy trì trạng thái online. |
| `0x11` | `USER_LIST` | UDP | Server $\rightarrow$ Client | Phát danh sách người dùng đang trực tuyến sau mỗi biến động mạng. |
| `0x20` | `MSG` | UDP | Peer $\leftrightarrow$ Server | Tin nhắn văn bản (Unicast/Broadcast) [Dành cho Step 5]. |
| `0x21` | `ACK` | UDP | Peer $\leftrightarrow$ Server | |

## 4. Message Payloads (JSON Schema)

### 4.1. Handshake Phase (TCP)

- **`0x01 HELLO_REQ`**:
  - Header: `Type: 0x01`, `Status: 0x00`, `Seq: 0`, `Len: 0`
  - Payload: Không có (Rỗng).

- **`0x02 HELLO_RESP`**:
  - Header: `Type: 0x02`, `Status: 0x01`, `Seq: 0`, `Len: 0`
  - Payload: Không có (Rỗng).

### 4.2. Authentication Phase (TCP)

- **`0x03 AUTH_REQ`**:
  - Header: `Type: 0x03`, `Status: 0x00`, `Seq: 0`, `Len: L`
  - Payload:

    ```json
    {
      "username": "alice",
      "udp_port": 9005
    }
    ```

- **`0x04 AUTH_RESP`**:
  - *Trường hợp thành công:*
    - Header: `Type: 0x04`, `Status: 0x01`, `Seq: 0`, `Len: L`
    - Payload:

      ```json
      {
        "session_id": "c1a2b3d4-e5f6-7890-abcd-ef1234567890",
        "message": "Authentication successful"
      }
      ```

  - *Trường hợp thất bại (Trùng Username / Sai thông số):*
    - Header: `Type: 0x04`, `Status: 0x02`, `Seq: 0`, `Len: L`
    - Payload:

      ```json
      {
        "error_code": "ERR_DUP",
        "message": "Username already exists"
      }
      ```

### 4.3. Session Termination Phase (TCP)

- **`0x05 LOGOUT_REQ`**:
  - Header: `Type: 0x05`, `Status: 0x00`, `Seq: 0`, `Len: L`
  - Payload:

    ```json
    {
      "session_id": "c1a2b3d4-e5f6-7890-abcd-ef1234567890",
      "username": "alice"
    }
    ```

- **`0x06 LOGOUT_RESP`**:
  - Header: `Type: 0x06`, `Status: 0x01`, `Seq: 0`, `Len: 0`
  - Payload: Không có (Rỗng).

### 4.4. Network Maintenance Phase (UDP)

- **`0x10 HEARTBEAT`**:
  - Header: `Magic: 0xDCBA`, `Type: 0x10`, `Status: 0x00`, `Seq: 0`, `Len: 0`
  - Payload: Không có (Rỗng để tối ưu tải đường truyền).
  - *Quy tắc xử lý phía Server:* Server dùng IP và Port nguồn của UDP datagram nhận được để tra cứu trong In-Memory Registry. Nếu tìm thấy, cập nhật `last_seen = current_time()`. Nếu chưa xác thực qua TCP, bỏ qua gói tin (Drop packet).

- **`0x11 USER_LIST`**:
  - Header: `Magic: 0xDCBA`, `Type: 0x11`, `Status: 0x01`, `Seq: N`, `Len: L`
  - Payload:

    ```json
    {
      "users": [
        {
          "username": "alice",
          "ip": "127.0.0.1",
          "udp_port": 9005
        },
        {
          "username": "bob",
          "ip": "127.0.0.1",
          "udp_port": 9006
        }
      ]
    }
    ```
## 5. Timing & Timeout Specifications

- **Heartbeat Interval (Client):** Định kỳ gửi gói `0x10 HEARTBEAT` mỗi **5 giây**.
- **Watchdog Check Interval (Server):** Luồng Watchdog quét kiểm tra danh sách kết nối mỗi **3 giây**.
- **Peer Expiration Timeout:** Nếu `current_time - last_seen > 15 giây`, Server tự động đánh dấu client là Dead Peer, đóng socket kết nối, xóa khỏi Registry và phát broadcast gói `0x11 USER_LIST` mới.
- **TCP Handshake / Auth Timeout:** Quá **5 giây** không hoàn tất phiên bắt tay sẽ tự động ngắt socket để chống nghẽn tài nguyên.