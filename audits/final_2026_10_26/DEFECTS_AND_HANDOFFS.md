# Defect register và bàn giao kỹ thuật

Không có bản sửa production được áp dụng. P1: phải giải quyết trước khi tuyên bố hoàn chỉnh/an toàn; P2: cần sửa hoặc ghi rõ giới hạn demo. “Owner” chỉ là nhóm cần phối hợp theo chức năng, không quy trách nhiệm cá nhân hay khẳng định commit gây lỗi nếu chưa bisect.

Phần số liệu gốc dưới đây là c892dc0. Late upstream84a69a8 chỉ guard ACK metadata; `upstream_84a69a8.diff` giữ diff chính xác. D01/D02/D06 đã tái hiện lại ở84 trong `http/http_latest.json` và `file_streaming/results_latest.json`; ca24MiB và strict có artifact latest riêng. P02–P07 không chạy lại ở84: đường code gây lỗi không đổi theo diff, vì vậy kết luận còn áp dụng dựa trên source equivalence, không gán bằng chứng thực thi sai commit. README chứa tổng hợp mới nhất.

## D01 — P1 — HTTP upload cùng tên có thể chuyển nhầm nội dung

- **Đã tái hiện hai lần**, `http/http_1.json`, `http/http_2.json`, test `test_concurrent_uploads_same_name_preserve_each_request_bytes`.
- Gửi `shared.txt` nội dung A cho Bob; trì hoãn worker ngay trước public `send_file`; gửi cùng tên nội dung B cho Cara. Sau khi Cara xong, cho worker Bob chạy. Cả receiver báo `completed`, nhưng Bob nhận B. SHA256 mong muốn A=`8f8234f5e9d5af22d696e7ab502d2876600bd5cb6d376c07edde9acbd0752c58`; thực nhận B=`400a5c8b1720140bf00d0ed44363670d5249712f64057e8f95cf68bd52238570`.
- **Gốc lỗi:** `client.py:UIHandler.do_POST` dùng chung `.upload_temp / basename`, ghi đè trước khi worker đọc. Hash và mã hóa ở tầng file kiểm tra đúng B nên không phát hiện sự thay thế xảy ra trước đó. Không phải SHA256 bị phá.
- Lịch chạy được điều khiển ở ranh giới thread, không thay networking/protocol, không chứng minh tần suất ngoài đời; đây là interleaving hợp lệ. Nhiều client UI chạy cùng cwd cũng chia staging directory. Tắt nút gửi trong một browser không giải quyết nhiều tab/client.
- **Owner:** người quản lý protected `client.py`, phối hợp Role4/Role3.
- **Sửa tối thiểu đề xuất:** staging directory riêng cho mỗi request/client, giữ basename gốc bên trong; worker sở hữu đường dẫn bất biến và cleanup trong finally sau khi đã tiêu thụ. Không chỉ đổi tên upload thành UUID nếu vô tình làm đổi tên file nhận. Trả operation id/error state cho UI.
- **Chấp nhận sửa:** cả hai SHA bằng từng file gốc trong schedule này; nhiều tab/client cùng cwd; cleanup không xóa file đang đọc.

## D02 — P1 — Sender báo done dù receiver đã failed

- **Đã tái hiện hai lượt gửi lại**, `file_streaming/results.json`: gửi `ordinary.bin` thành công, đổi bytes nhưng giữ tên và gửi lại. Receiver giữ file cũ, `failed: destination exists`; sender `done`,100%. Không mất gói được tiêm vào ca này.
- **Gốc lỗi:** `file_transfer.py:FileReceiver.accept_chunk` xóa incoming khi finalize lỗi. `file_client.py:FileTransferHandler._on_chunk` ACK cả kết quả `ignored` trước khi return. Retransmission sau failure vì vậy nhận ACK và `_send_worker` suy ra done. Fix final-ACK cũ quá rộng: thành công và thất bại bị gộp thành cùng “không còn incoming”.
- **Owner:** Role3; protocol status cần phối hợp Role1.
- **Đề xuất:** cache terminal outcome có thời hạn theo transfer_id/peer; chỉ lặp successful ACK cho chunk thuộc transfer đã hoàn tất xác minh; explicit failure/NACK hoặc completion response cho failed/expired; sender xác nhận receiver finalize thay vì chỉ đủ chunk ACK. Giữ chính sách không overwrite file đích nếu đó là ý định, nhưng báo thật ở cả hai đầu.
- **Chấp nhận sửa:** final ACK loss vẫn recover; destination collision/hashing/disk-write failure phải báo failure ở sender, receiver; không có `done` khi bytes chưa commit. D09 phải cùng được xử lý.

## D03 — P1 — Private chat vẫn plaintext

- **Hai lần P02 FAIL**, `protocol_security/results_initial.json`, `results.json`. Raw TCP peer đọc được `AUDIT_PRIVATE_PAYLOAD_20261026` trong JSON, không decrypt. Đây là dữ liệu tự tạo trên localhost.
- **Gốc lỗi:** `client.py:send_message`/`_send_tcp` encode JSON trực tiếp; `server.py:handle_msg_data` forward JSON; không TLS hoặc payload encryption trên luồng chat. File Fernet không bao phủ chat.
- **Owner:** Roles2/3 + Role1 khi đổi wire contract.
- **Đề xuất:** chốt mô hình key/trust rồi bảo vệ payload chat bằng thư viện chuẩn hoặc TLS trên control/chat channel; phối hợp encode/decode/error/length budgets hai phía. Không tự viết crypto. Mã hóa file bằng key có sẵn trong repository chỉ là demo standard-library crypto, không bảo vệ trước người biết key.
- **Chấp nhận sửa:** cùng marker không xuất hiện raw wire, đúng recipient decrypt; malformed ciphertext bị loại, reconnect/maximum payload vẫn có lỗi có kiểm soát. Không ghi credentials/key vào log.

## D04 — P1 — UDP discovery thiếu kiểm tra nguồn và schema; receive thread có thể chết âm thầm

- **Hai lần P03/P04 FAIL**: một nguồn localhost không thuộc server thay `users` và `peer_addrs`; JSON list `[]` gây `AttributeError: 'list' object has no attribute 'get'`. UDP thread chết, `stop_event=False`, TCP chat vẫn chạy; client không thấy user mới.
- Bằng chứng nguồn gửi khác port19001, trạng thái thread và exception nằm trong JSON; phạm vi chỉ disposable test clients, không thiết bị bên ngoài.
- **Gốc lỗi:** `client.py:CollaborationClient._udp_receive_loop` nhánh MSG_USER_LIST không kiểm tra `addr`, gọi `.get` trước kiểm tra top-level object, cập nhật users trước khi validate toàn snapshot; exception set không gồm AttributeError.
- **Owner:** Role1, protected client integration.
- **Đề xuất:** canonicalize/check địa chỉ server, validate cả object/list/rows/ports, tạo snapshot mới rồi commit nguyên tử; reject invalid packet mà tiếp tục loop. Source check là bước tối thiểu, không thay thế authenticated discovery nếu threat model cần chống spoof trên LAN.
- **Chấp nhận sửa:** P03/P04 pass; sau packet bị loại vẫn nhận user mới và file. Thread death phải hiện lỗi phiên nếu không thể phục hồi. Không chỉ `except Exception: pass` để giấu trạng thái hỏng.

## D05 — P1 — Snapshot user cũ làm mất peer đang online

- **Hai lần P05 FAIL**, dùng chính packet server đã phát và replay từ chính socket server để mô phỏng UDP trễ, không cần giả mạo nguồn. Sau snapshot mới có observer+alice, snapshot cũ chỉ observer ghi đè; qua5.3s/heartbeat vẫn sai. Không đóng TCP.
- **Gốc lỗi:** `server.py:broadcast_user_list` không có generation/version (`seq=0`); client nhận snapshot nào cũng dùng. Không periodic refresh/resync sau loss. Parallel register có thể làm emission khác thứ tự snapshot.
- **Owner:** Role1.
- **Đề xuất:** generation có server epoch, cập nhật khi registry đổi và serialize snapshot/version; client bỏ older generation; có refresh/resync để mất snapshot cuối không stale mãi. Chỉ check IP/port ở D04 không sửa D05.
- **Chấp nhận sửa:** delayed/duplicate/lost final discovery update,20 connect/disconnect; mọi client converge về registry, gồm server restart có epoch mới. Test20 client happy path xanh không thay bài thử này.

## D06 — P1 nếu dùng cho milestone streaming — EOF nằm trong dữ liệu làm mất bytes

- `file_streaming/results.json`: standalone payload7 bytes `__END__` →0 bytes, sender success/finished và receiver complete;707 bytes gồm700x rồi marker →700 bytes. Marker7 bytes lặp lại vẫn mất. Empty stream returnsTrue nhưng sender_finished/receiver_complete=False.
- **Giới hạn quan trọng:** runtime file tích hợp truyền đúng literal `__END__` và empty file trong cùng audit. Lỗi này ở `udp_streamer.py`, không quy là mọi file qua UI bị cắt marker.
- **Gốc lỗi:** `UDPStreamReceiver.handle_packet` nhận diện END bằng so sánh payload với `END_FLAG`; `UDPStreamSender.send_data` early return với empty; `_send_end` gửi3 lần không chờ final completion ACK.
- **Owner:** Role2.
- **Đề xuất:** EOF ở message type/flag độc lập payload + expected length/transfer identity; empty stream vẫn đóng hợp lệ; completion/ACK retry đúng trạng thái. Chốt semantics multi-stream và sequence wrap trước tích hợp.
- **Chấp nhận sửa:** byte-exact cho mọi chuỗi, marker ở mọi vị trí, empty complete hai phía, lost-END/ACK kết quả thật; kiểm tra1 stream không chặn stream khác.

## D07 — P2 — Frame chat hợp lệ sát giới hạn làm session bị ngắt

- **Hai lần P06 FAIL**: input JSON65535 bytes hợp lệ header16bit, text65481 bytes; không delivery, không error response, sender đóng. Server log: `server.py:_send_safely` → `protocol.py:encode_packet` → `struct.error: 'H' format requires 0 <= number <= 65535`.
- **Gốc lỗi:** forwarding thêm `sender` khiến output lớn hơn header cho phép; encode error không nằm trong lỗi xử lý. Không phải browser mặc định gửi quá5000 ký tự.
- **Owner:** Roles1/2. **Đề xuất:** validate serialized forwarded payload trước send, define message limit gồm overhead và escaped Unicode, trả STATUS_ERR cho sender; không terminate session. Nếu fragmentation được yêu cầu phải thiết kế ở protocol, không UI workaround.

## D08 — P2 — UDP port không hợp lệ vẫn AUTH_OK

- **Hai lần P07 FAIL**: udp_port70000 trả AUTH_OK, rồi `OverflowError: sendto(): port must be 0-65535` ở `server.py:broadcast_user_list`; session thread lỗi. Một client hợp lệ kế tiếp vẫn auth được: không gọi đây là toàn server crash.
- **Owner:** Role1. **Đề xuất:** validate integer thật,1..65535 trước registry; giới hạn username/schema; ERR cụ thể và rollback registration nhất quán. Test boundaries0/65535/65536, negative, bool/string tùy contract, server vẫn sống.

## D09 — P1 — Transfer vẫn hoạt động bị timeout theo tuổi; sender sau đó báo done

- `file_streaming/large_file_results.json`: **24MiB hợp lệ**, không tiêm loss, không tăng tốc clock, port29000/29001. Sau163.544s sender done100%; receiver timeout75%; không có destination. Sample140s vẫn receiving69%,150s timeout75%. Lần lặp riêng `large_file_repeat.json` sau163.941s: sender done100%, receiver timeout74%, vẫn không có destination. Không còn network test khác chạy đồng thời ở lần lặp.
- `FileReceiver.cleanup_expired` dùng `now-created_at >120`, không last activity; client cleanup mỗi30s. Dữ liệu vẫn đang đến bị xóa. D02 tiếp tục ACK ignored chunks, đẩy sender tới done dù không file.
- `IncomingFile.missing_chunks` dựng list toàn bộ range và được gọi nhiều lần trên mỗi chunk; kết hợp whole-file RAM, retry/pacing cố định làm tải lớn chậm. Đây là phân tích source về chi phí; chưa có profiler để quy mọi thời gian cho một hàm.
- **Owner:** Role3. **Đề xuất:** expiry idle dựa monotonic last_activity + giới hạn tổng riêng có chủ đích, terminal failure signaling, counter/bitmap missing thay rescan O(n) từng chunk; resource bounds. Tăng120 thành số lớn hơn đơn thuần không sửa false success.
- **Chấp nhận sửa:** file trong giới hạn với tốc độ chậm nhưng tiến triển hoàn tất đúnghash; stalled file thật phải timeout; sender/receiver đồng thuận; test24MiB và sátlimit trên LAN. Không coi thời lượng đo trên máy audit là cam kết performance.

## Gaps và rủi ro chưa được chứng minh bằng một failure runtime

| ID / ưu tiên | Bằng chứng hiện có | Handoff / bước xác minh |
|---|---|---|
| R01 / P1 nộp bài | Chưa thấy technical report PDF; README thiếu startserver/client; pytest undeclared và command thực báo missing module | Team hoàn thiện report đúng4 mục đề, README; dựng venv sạch và chạy theo chính README. Audit không sửa shared docs. |
| R02 / P1 rubric | Không tích hợp UDPStream; không thấy BBR/CUBIC, async byte consumer; đề có chỗ TCP/UDP mâu thuẫn | Role1/2 trình bày actual data path, hỏi giảng viên phạm vi; thống nhất contract rồi tích hợp, không chỉ thêm tên module. |
| R03 / P2 UX | state thiếu server connectivity/worker error; UI ghi unknown và HTTP accepted trung thực | Protected client thêm verified session state/timestamp/operation errors; Role4 render sau khi contract được chốt. |
| R04 / P2 tải lâu | client.messages, transfers/progress, upload staging giữ lâu; `_pending` window có đường exception trước unregister | Chạy soak/RSS/file-count; finally cleanup waits và bounded history; chưa đo leak bằng soak nên gọi risk, không claimed crash. |
| R05 / P2 HoL | server synchronous sendall theo thứ tự broadcast, không timeout sauauth; thread perconnection không chống slowreader hoàn toàn | Thử bounded nonreading peer, healthy unicast/broadcast latency; perpeer outbound queue/backpressure khi có bằng chứng. Chưa chạy trong audit này. |
| R06 / P2 security | Username registration không verify password; shared static Fernet key; HTTP không auth/Origin policy | Không phải tự động trừ milestonelogin. Chốt threat model LAN/local bridge, keydistribution/perpeer binding. Chưa chạy crossorigin browser attacks; không tuyên bố khả năng khai thác đã chứng minh. |
| R07 / P2 test quality |3 marker expectedFailure cũ trở thành unexpectedSuccess; standalone empty test chỉ so bytes, không đòi receivercomplete | Role4 bỏ marker sau review riêng; mở rộng terminal-state assertions; không thay thế test hiện có bằng kiểm tra yếu hơn. |
| R08 / chưa kiểm chứng | LAN2máy, macOS/Linux, max82.5/100MiB, congestion/fairness, soak, sequencewrap, diskfull, arbitrary file-packet corruption chưa chạy | Ưu tiên sau D01–D09; không gắn nhãn PASS. Một nhánh file-packet bất thường bị automatic review chặn; đã thu hẹp sang file hợp lệ, không thử lại thao tác bị chặn. |

## Thứ tự khắc phục đề nghị

1. D01/D02/D09: bảo toàn nội dung người dùng và trạng thái kết quả thật.
2. D03/D04/D05: hoàn thiện bảo vệ payload, receive-loop resilience và discovery convergence.
3. D06/R02: chứng minh streaming abstraction theo yêu cầu đã chốt; D07/D08 validate biên.
4. R01/R07: hoàn chỉnh hồ sơ nộp và test runner; rerun strict + audit failures rồi LAN/soak.

Không đóng ticket bằng cách skip/expectedFailure, tăng sleep, hoặc đổi assertion cho khớp lỗi. Mỗi handoff cần cả phản ví dụ hết lỗi và regression cũ không hỏng.
