# Audit file transfer / UDP streaming — 26-10-2026

Baseline phần báo cáo gốc này: `c892dc02aa081c10a49cba4709b058ebe9d0d0bd`, kết quả giữ trong `results_c892dc0.json`. Rerun84a69a8 nằm ở `results_latest.json`; xem README tổng để biết metric mới, không dùng thời gian4.390s dưới đây cho84.
Chỉ thêm artifact trong thư mục audit này; không sửa production hoặc test cũ.

## Phương pháp và kết quả thật

Chạy tại root repository bằng Python `.venv` hiện có trên Windows:

```powershell
.\.venv\Scripts\python.exe -X utf8 audits/final_2026_10_26/file_streaming/functional_audit.py
```

Lần có JSON đính kèm: exit code **1**, thời gian nội bộ **4.390 giây**. Exit 1 giữ nguyên các lỗi quan sát được, không có expectedFailure/skip. `results.json` lưu trạng thái, SHA-256, thống kê; `execution.txt` lưu stdout/stderr. `server.log` là log phụ; audit có ngoại lệ ignore riêng để lưu evidence. Positive control dùng public CollaborationClient API, không phải HTTP trong audit con này.

Test khởi động server thật và hai `CollaborationClient` thật, đợi discovery thật; chỉ override host/port trong process test sang loopback TCP 29000 / UDP 29001. Bind kiểm tra trước, không giải phóng port bằng cách kill process khác. File/download nằm trong TemporaryDirectory và được dọn sau khi đóng client/server thuộc test. Standalone streamer chạy qua hai socket UDP loopback ephemeral thật. Không mock ACK, không packet mutation, không malformed/security injection.

10 quan sát (bao gồm lặp tái hiện, **không phải 10 yêu cầu độc lập**): 4 quan sát đạt, 6 quan sát thể hiện lỗi, tương ứng **3 lỗi khác nhau**.

| Trường hợp | Kết quả quan sát |
|---|---|
| File binary 1.024 byte qua client/server | Sender `done`, receiver `completed`, SHA-256 trùng |
| Gửi lại cùng tên với nội dung mới 1.320 byte | Sender `done` 100%; receiver `failed: destination exists`; file đích vẫn là nội dung cũ |
| Lặp gửi lại cùng tên lần nữa | Tái hiện cùng lỗi |
| File rỗng qua client/server | Hai phía thành công; file đích 0 byte |
| File 7 byte `__END__` qua client/server | Hai phía thành công, byte-exact |
| Standalone streamer binary 1.024 byte | Hai phía hoàn tất, byte-exact, SHA-256 trùng |
| Standalone streamer 7 byte `__END__` | Sender thành công, receiver hoàn tất nhưng nhận **0 byte** |
| Standalone streamer 700 byte `x` rồi `__END__` | Sender thành công, receiver hoàn tất nhưng nhận **700/707 byte** |
| Lặp standalone 7 byte `__END__` | Tái hiện mất toàn bộ 7 byte |
| Standalone stream rỗng | `send_data()` trả True nhưng `sender.is_finished=False`, `receiver.is_complete=False`, không có datagram nào |

## FS-01 — P1: sender báo hoàn tất dù receiver từ chối file trùng tên

**CONFIRMED — Role 3, đường chạy tích hợp thực tế.** Lặp 2 lần mỗi lần chạy. Không phải lỗi môi trường hoặc chỉ lỗi UI. Tránh ghi đè file đích là hành vi bảo vệ hợp lý; lỗi là thông báo thành công giả ở sender.

Tái hiện: gửi `ordinary.bin` chứa `bytes(range(256))*4`; giữ nguyên file đích; thay file nguồn bằng `b'new content with the same filename'*40`, gửi lại đến cùng người. Sender `done`/100 và receiver `failed: destination exists`/100 xuất hiện trong chính `CollaborationClient.state()`.

SHA-256 nội dung mới cần nhận: `bd23800673e4affd0ba4bf6f80fd91fd0e755bf85f7c09166664905d1cc87c38`.
SHA-256 file đích thực tế: `785b0751fc2c53dc14a4ce3d800e69ef9ce1009eb327ccf458afe09c242c26c9` (nội dung cũ).

Nguyên nhân theo code:

1. `file_transfer.py:391`, `FileReceiver.accept_chunk`: khi đích đã tồn tại, ghi failed rồi xóa transfer khỏi `incoming`.
2. Sender retry chunk chưa ACK. `file_transfer.py:314` coi mọi file_id không còn trong incoming là `ignored`, không phân biệt completed và failed.
3. `file_client.py:260`, `_on_chunk` vẫn `_reply_ack` trước kiểm tra `ignored`.
4. `file_client.py:111`, `_send_worker` suy ra `done` khi đã có ACK mọi chunk, không xác nhận receiver lưu file thành công.

Handoff tối thiểu: giữ terminal outcome có giới hạn cho từng transfer; chỉ ACK retry như thành công nếu outcome thực sự completed. Với rejected/failed cần phản hồi thất bại hoặc để sender timeout, tuyệt đối không ACK kiểu dẫn tới done. Ưu tiên completion/error acknowledgement rõ nghĩa và sender kiểm tra completion sau SHA-256 + ghi file. Phân biệt duplicate thành công với transfer thất bại/hết hạn; giữ tính phục hồi lost-final-ACK. Acceptance: trường hợp collision trên phải giữ file cũ và sender không được done; file tên mới phải thành công/hash đúng; lost-final-ACK sau completion hợp lệ vẫn phục hồi. Không đề nghị sửa UI để che trạng thái backend sai.

## FS-02 — P1 nếu standalone streamer là phần được đánh giá: delimiter làm hỏng binary hợp lệ

**CONFIRMED — Role 2, `udp_streamer.py`; chưa phải lỗi file runtime tích hợp.** Binary bất kỳ có thể chứa đúng byte marker, không cần mất gói hoặc input sai định dạng.

`END_FLAG=b"__END__"` tại dòng 31; `UDPStreamReceiver.handle_packet` dòng 308 nhận diện kết thúc bằng payload equality. Data và END cùng msg_type nên một data chunk hợp lệ trùng marker bị hiểu là END. Receiver ACK trước khi phân loại; sender nhận đủ ACK và báo thành công.

Handoff: tách control END khỏi không gian giá trị byte dữ liệu bằng header/type/flag hoặc metadata length rõ nghĩa; completion phải tương ứng toàn bộ byte dữ liệu. Không cấm một mẫu binary hợp lệ. Acceptance: b`__END__`, marker ở cuối chunk và payload binary thường phải byte-exact; sender/receiver completion nhất quán. Kiểm tra thêm partial marker/chunk boundary sau thay đổi.

Phạm vi: `client.py:38,70,260` dùng `FileTransferHandler`; không import `UDPStreamSender/Receiver`. File `literal_marker.bin` qua API tích hợp đã thành công, nên **không quy lỗi này cho file transfer tích hợp**. Tuy nhiên không thể dùng test standalone xanh trước đây làm bằng chứng UDP byte stream không corruption.

## FS-03 — P2: stream rỗng trả thành công nhưng không hoàn tất phiên

**CONFIRMED — Role 2 standalone, `udp_streamer.py:61`.** Early return trước reset state/gửi END làm bên nhận không có tín hiệu hoàn tất; so sánh `b'' == b''` đơn thuần sẽ cho green sai. Handoff: empty stream phải đi qua lifecycle rõ ràng và receiver nhận completion, hoặc công khai từ chối empty bằng kết quả lỗi nhất quán. Acceptance phải kiểm tra cả completion hai phía và bytes, không chỉ equality. File rỗng tích hợp đã thành công và không bị lỗi này.

## Bằng chứng kiến trúc và khoảng trống yêu cầu

Các mục sau là **inspection**, không biến thành kết quả benchmark hay thử nghiệm lỗi:

- PDF đề bài trang 2 yêu cầu sequencing/window/selective retry, async byte-chunk UDP stream tránh HoL, và có nêu BBR/CUBIC; milestone 6 yêu cầu file UDP không corruption. `file_client.py:111` có fixed batch window và retry chunk chưa ACK; vòng lặp đợi cả batch mới sang batch tiếp. `udp_streamer.py` có sliding window/selective retry riêng. Không tìm thấy BBR/CUBIC trong hai đường này; fixed window không chứng minh congestion control. Cần thống nhất mức yêu cầu với giảng viên, không tự coi là tùy chọn.
- `UDPStreamSender.send_data()` nhận toàn bộ bytes và blocking cho tới xong; `UDPStreamReceiver.get_data()` cho snapshot prefix liên tục, `_try_assemble` chờ `expected_seq`. Không có async iterator/callback chunk-ready. Việc dùng thread trong ứng dụng giúp UI không nhất thiết block nhưng chưa chứng minh đáp ứng async fetch/HoL trong đề. Standalone module chưa được runtime client/server gọi; phải chỉ ra luồng tích hợp thực tế khi bảo vệ bài.
- `file_transfer.py:29` khai báo 100 MiB, `from_path:158` kiểm tra stat rồi `read_bytes`, `from_bytes:137` chia tất cả chunk trước gửi. Receiver lưu chunks trong RAM, join toàn bộ trước SHA-256/ghi file. `IncomingFile.missing_chunks:217` duyệt tất cả chỉ số, được gọi nhiều lần/chunk tại `accept_chunk:366,372`: rủi ro CPU/RAM với file lớn. **Chưa đo file sát 100 MiB; không kết luận mọi file trong limit đều hoạt động hiệu quả.**
- `_send_end:187` gửi END ba lần, sender đánh dấu success ở dòng 128 ngay sau đó; không chờ receiver xác nhận completion. Đây là code-level reliability risk, **chưa fault-inject mất END** trong audit con này.
- Chỉ test hợp lệ loopback nhỏ; không benchmark LAN/WAN, băng thông cao, 100 MiB, nhiều file đồng thời, disk full, mất/reorder packet trong bộ audit con này. Kết quả regression/fault tests của audit tổng phải dẫn artifact riêng, không gán vào các thử nghiệm ở đây.

## Kết luận phạm vi

Đã chứng minh đường file tích hợp truyền đúng binary nhỏ/rỗng và giữ file có sẵn, nhưng có lỗi quan trọng sender báo thành công giả khi gửi lại tên cũ. Standalone streamer hỏng dữ liệu binary hợp lệ và empty completion. Do đó chưa thể tuyên bố hoàn tất tin cậy end-to-end hoặc byte streaming arbitrary-data đúng chỉ dựa trên các test cũ. Không chỉnh sửa Roles 1–3; mọi sửa chữa nêu trên là handoff.
