"""Build the Role 4 technical submission report from verified local evidence."""
from pathlib import Path
import json
from html import escape
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Flowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output/pdf"
OUT.mkdir(parents=True, exist_ok=True)
pdfmetrics.registerFont(TTFont("Arial", "C:/Windows/Fonts/arial.ttf"))
pdfmetrics.registerFont(TTFont("ArialBold", "C:/Windows/Fonts/arialbd.ttf"))
pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="ArialBold", italic="Arial", boldItalic="ArialBold")
styles = getSampleStyleSheet()
for style in styles.byName.values():
    style.fontName = "Arial"
styles.add(ParagraphStyle(name="BodyVN", fontName="Arial", fontSize=10.2, leading=15, spaceAfter=9))
styles.add(ParagraphStyle(name="SmallVN", fontName="Arial", fontSize=8.4, leading=11, spaceAfter=5))
styles["Title"].fontName = styles["Heading1"].fontName = styles["Heading2"].fontName = "ArialBold"
styles["Title"].fontSize, styles["Title"].leading = 25, 32
styles["Heading1"].fontSize, styles["Heading1"].leading = 18, 23
styles["Heading2"].fontSize, styles["Heading2"].leading = 12, 17
navy, teal = colors.HexColor("#16384a"), colors.HexColor("#08695e")
for name in ("Title", "Heading1", "Heading2"):
    styles[name].textColor = navy
story = []
def p(text, style="BodyVN"):
    story.append(Paragraph(text, styles[style]))
def h(text):
    p(text, "Heading1")
def table(rows, widths):
    data = [[Paragraph(escape(str(cell)), styles["SmallVN"]) for cell in row] for row in rows]
    item = Table(data, colWidths=widths, hAlign="LEFT", repeatRows=1)
    item.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e3ecee")),
        ("VALIGN", (0,0), (-1,-1), "TOP"), ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 7), ("LINEBELOW", (0,0), (-1,-1), .4, colors.HexColor("#ccd8dc"))]))
    story.append(item)
    story.append(Spacer(1, 12))
class Architecture(Flowable):
    def __init__(self):
        super().__init__()
        self.width, self.height = 475, 190
    def draw(self):
        c = self.canv
        labels = [(0,130,145,40,"Browser Alice / Bob"),(185,130,290,40,"Local HTTP + CollaborationClient"),
                  (185,55,290,43,"TCP server: registry + routing"),(0,0,475,36,"FileTransferHandler + FileReceiver: UDP trực tiếp giữa peers")]
        c.setFont("Arial",9)
        for x,y,w,hh,label in labels:
            c.setFillColor(colors.HexColor("#eef4f5")); c.setStrokeColor(teal)
            c.roundRect(x,y,w,hh,5,stroke=1,fill=1)
            c.setFillColor(navy); c.drawCentredString(x+w/2,y+hh/2-3,label)
        c.setStrokeColor(teal)
        c.line(145,150,185,150); c.line(330,130,330,98)
        c.line(150,55,150,36); c.line(185,150,150,150); c.line(150,150,150,55)
        c.setFont("Arial",8)
        c.drawString(334,112,"TCP chat/control; UDP discovery")
        c.drawString(2,75,"GET state / POST send,file")
class Sequence(Flowable):
    width = 475
    def __init__(self, actors, steps):
        super().__init__(); self.actors=actors; self.steps=steps
        self.width = 475
        self.height = 62 + 42 * len(steps)
    def draw(self):
        c=self.canv; xs=[35+i*(405/(len(self.actors)-1)) for i in range(len(self.actors))]
        top=self.height-18
        c.setFont("ArialBold",8.4); c.setFillColor(navy)
        for x,name in zip(xs,self.actors):
            c.drawCentredString(x,top,name)
            c.setStrokeColor(colors.HexColor("#c1cdd1")); c.setDash(2,3)
            c.line(x,top-8,x,10); c.setDash()
        for i,(a,b,label) in enumerate(self.steps):
            y=top-40-i*42; x1,x2=xs[a],xs[b]
            c.setStrokeColor(teal); c.line(x1,y,x2,y)
            sign=1 if x2>x1 else -1
            c.line(x2,y,x2-sign*5,y+3); c.line(x2,y,x2-sign*5,y-3)
            c.setFont("Arial",8.2); c.setFillColor(navy)
            c.drawCentredString((x1+x2)/2,y+7,label)

p("ASSIGNMENT 1", "Heading2")
p("Distributed &amp; Streaming-based<br/>Client-Server Collaboration", "Title")
p("Báo cáo kỹ thuật và xác minh tích hợp", "Heading1")
p("Role 4 - Client, UI &amp; Testing | 05/11/2026")
p("<b>Baseline:</b> 3c4174791a7e796a18e6d57c98c03111359cc1a5. Báo cáo mô tả implementation thực tế và bằng chứng kiểm thử, không xác nhận mọi yêu cầu đã đạt. Source Roles 1-3 không bị thay đổi bởi đợt finalization.")
story.append(Architecture())
p("<b>Luồng đang chạy:</b> browser dùng HTTP cục bộ để gọi client hiện có. TCP phục vụ handshake, login và chat; UDP phục vụ heartbeat/discovery và file P2P. File được chia chunk 700 byte, gửi cửa sổ8, kiểm SHA-256 trước ghi đích. Nội dung chat và file dùng Fernet từ thư viện cryptography.")
p("<b>Ranh giới kiến trúc:</b> static/index.html chỉ trình bày; client.py chứa HTTP bridge và socket client; server.py quản lý phiên và routing; file_client.py điều phối ACK/transfer; file_transfer.py mã hóa, serialization và reassembly. udp_streamer.py là module riêng, chưa được runtime này sử dụng.")
p("Đề gốc: Assignment 1 PDF trang 1-4, SHA256 c16b856e…819f567. Guide slide7/18/22 nêu các điểm cần chốt về transport, congestion và HTTP UI. Không lấy starter demo làm chuẩn thay đề.", "SmallVN")
story.append(PageBreak())
h("1. Protocol và phiên làm việc")
p("Header chung TCP/UDP dùng network byte order, struct !HBBHH, dài8 byte. TCP đọc đủ header rồi đúng payload_length; UDP chứa một packet mỗi datagram. Header và routing metadata không được coi là encrypted.")
table([["Trường", "Độ dài", "Ý nghĩa"],["Magic","2 byte","0xDCBA"],["Message type","1 byte","HELLO, AUTH, LOGOUT, heartbeat/user list, DATA/ACK/EOF"],["Status","1 byte","0:none, 1:OK, 2:error"],["Sequence","2 byte","0..65535; wrap cần semantics riêng theo từng luồng"],["Payload length","2 byte","0..65535 byte, không gồm header"]],[120,80,275])
table([["Kênh / message", "Payload và hành vi hiện tại"],["TCP HELLO/AUTH/LOGOUT","AUTH: username + udp_port; reply session_id. Không có password database. Server reject tên trùng và cổng ngoài1..65535."],["TCP DATA","JSON mode/broadcast hoặc unicast, recipient, message chứa Fernet token, enc:true. Server thêm sender và forward; client decrypt message."],["UDP heartbeat/discovery","Peer gửi heartbeat mỗi5s; server watchdog15s và quét3s. Snapshot user cóseq, client kiểm source/schema/order; server refresh định kỳ."],["UDP DATA file","Encrypted JSON FILE_META, FILE_CHUNK, ACK và FILE_RESULT. file_id/chunk_index thuộc application payload. FILE_RESULT thông báo completed/failed."],["Standalone streaming","MSG_EOF riêng sau fix; không còn dùng literal payload làm EOF. Vẫn cần chứng minh tích hợp và congestion control."]],[135,340])
p("<b>State phiên:</b> START → TCP CONNECT → HELLO_OK → AUTH_OK → ACTIVE → LOGOUT/CLOSED. API state trả username, users, messages, transfers. HTTP thành công chỉ chứng minh bridge còn sống; chưa có verified server-liveness field. Tự nối lại phiên sau server restart chưa được triển khai.")
p("<b>Giới hạn security:</b> Fernet key chung trong config chỉ phù hợp demo. Người biết key có thể decrypt/forge; không gọi đây là bảo mật danh tính end-to-end. Mã hóa chat mặc định không đồng nghĩa server bắt buộc mọi raw peer gửi ciphertext.")
story.append(PageBreak())
h("2. Sequence: login và message")
story.append(Sequence(["Browser A","Client A","Server","Client B"],[(1,2,"TCP HELLO → HELLO_RESP"),(1,2,"AUTH username/udp_port → session"),(2,1,"UDP USER_LIST snapshot"),(0,1,"POST /api/send {to,text}"),(1,0,"HTTP accepted (không phải delivered)"),(1,2,"TCP DATA: Fernet message + routing"),(2,3,"Forward DATA tới đúng recipient"),(3,2,"Heartbeat UDP độc lập"),(0,1,"GET /api/state để render snapshot")]))
p("Client gửi lưu local message record sau sendall; không có ACK ứng dụng xác nhận người nhận đọc/hiển thị chat. Broadcast server gửi tới các peer khác; unicast gửi đúng username. Client B decrypt rồi thêm message vào state. UI không được đổi nhãn HTTP accepted thành delivered.")
p("<b>Concurrency:</b> mỗi TCP session có thread; client có TCP receive, UDP receive, heartbeat và cleanup threads. Server dùng lock cho registry/send. Điều này hỗ trợ20 client đã kiểm, nhưng chưa chứng minh fairness/latency dưới slow-reader hoặc soak dài.")
p("<b>Ordering:</b> TCP bảo đảm thứ tự byte trong một connection. UDP snapshot version giảm stale update; byte streaming async và loại bỏ HoL giữa logical streams chưa được chứng minh chỉ bằng việc có thread.")
story.append(PageBreak())
h("3. Sequence: file và completion")
story.append(Sequence(["Browser A","Client A","Peer B"],[(0,1,"POST /api/file: name + Base64"),(1,0,"HTTP accepted sau staging/worker start"),(1,2,"Encrypted FILE_META + SHA256"),(2,1,"ACK metadata (index=-1)"),(1,2,"Window FILE_CHUNK; retry missing ACK"),(2,1,"ACK từng chunk được chấp nhận"),(2,1,"FILE_RESULT sau verify/hash/write"),(0,1,"GET state: progress + terminal status")]))
p("Receiver kiểm file size, chunk index, size/hash và đường dẫn. File đích tồn tại được từ chối để tránh overwrite. Sender mới dựa FILE_RESULT để biết completed/failed; tuy nhiên kết quả cuối vẫn phải đáng tin khi chính datagram result/ACK bị mất.")
p("<b>Hai ranh giới cần review:</b> staging hiện dùng .upload_temp/basename nên request đồng thời trùng tên có thể thay bytes trước khi worker đọc. Sau đó SHA256 vẫn đúng đối với bytes đã bị thay, không còn đại diện file người gửi chọn. Ngoài ra trạng thái done phải ổn định sau worker kết thúc, không chỉ đúng tại một lần poll.")
p("<b>UI:</b> upload 110MiB JSON tương đương khoảng82.5MiB raw file; layer file 100MiB. UI tính cả Base64/JSON overhead. Progress100 với status sending được ghi rõ 'Chờ kết quả từ bên nhận'; không giả completed. Draft/file được giữ khi HTTP operation thất bại.")
story.append(PageBreak())
h("4. Verification và khả năng tái lập")
rows=[["Lượt Role4", "Total / pass / fail / error", "Thời gian"]]
for name in ("initial_strict", "final_1", "final_2"):
    path=ROOT/"audits/finalization_2026_11_05"/(name+".json")
    if path.exists():
        data=json.loads(path.read_text(encoding="utf-8"))
        rows.append([name, " / ".join(str(data[k]) for k in ("total","pass","fail","error")), str(data["duration_seconds"])+"s"])
table(rows,[130,230,115])
p("Các JSON/traceback gốc trong audits/finalization_2026_11_05. Initial suite có21 test; final suite bổ sung lost-result và same-name upload thành23. Không thêm skip/expectedFailure. Lỗi disk của fixture83MiB được sửa bằng browser File thật cùng size trong RAM; đây là test validation, không giả truyền83MiB qua mạng.")
p("<b>Kiểm chứng dương:</b> server + client.main thật serve HTML, real HTTP chat/file, SHA256, progress;20 client đồng thời; kill client, heartbeat timeout, restart thủ công; browser malformed state/XSS/draft/API timeout/mobile/keyboard. Test backend/review bổ sung độc lập nằm trong các thư mục con tương ứng.")
p("<b>Bổ sung:</b> file 24MiB hoàn tất55.653s, SHA-256 khớp và progress trung gian. Receiver timeout đã qua real HTTP và Edge DOM. Team file tests:29 pass / 6 fail do contract drift. Review phát hiện username '*' xung đột broadcast và client không có deadline đọc HELLO.")
p("<b>Test không đủ để suy ra:</b> DOM fixture không chứng minh sockets; boolean sender không chứng minh receiver commit; completed tức thời không chứng minh terminal status ổn định. Test mới quan sát qua retry horizon và so bytes người gửi chọn với file nhận.")
p("<b>Chạy:</b> python -m unittest discover -s tests -p \"test_role4_*.py\" -v. Demo có cleanup: python submission/assignment1/demo.py --smoke --output demo-result.json. Xem submission/assignment1/README.md để cài runtime/test dependencies và chạy3 terminal.")
p("<b>Chưa kiểm chứng:</b> LAN nhiều máy, file sát100MiB/HTTP limit, diskfull có kiểm soát, prolonged soak, slow-reader fairness, BBR/CUBIC, simulator/OS khác. Disk gần đầy là môi trường giới hạn thật, không phải lý do bỏ invariant hay che failure.")
story.append(PageBreak())
h("5. Challenges &amp; Solutions")
p("Trang reflection này tổng hợp bài học có bằng chứng từ implementation, Git và phép thử. Nhóm cần duyệt nội dung và bổ sung trải nghiệm cá nhân trước khi nộp; không tự gán ai đã làm công việc chưa được xác nhận.")
p("<b>Độ tin cậy có nhiều tầng.</b> HTTP200 chỉ xác nhận bridge nhận yêu cầu; sendall chỉ gửi bytes cho TCP; chunk ACK chỉ xác nhận một bước trong file transfer. Trước đây sender có thể báo done khi receiver từ chối file. Upstream thêm FILE_RESULT để tách kết quả receiver khỏi ACK chunk. Bài học là cần đặc tả terminal outcome rõ ràng, bounded retry cho completion, và kiểm tra cả hai phía cùng nội dung trên đĩa.")
p("<b>Race xảy ra trước khi network protocol bắt đầu.</b> Hai upload cùng basename ghi chung staging có thể làm worker đầu đọc file của request sau. Mã hóa và checksum không giải quyết thay thế trước bước tính hash. Giải pháp bàn giao là staging riêng cho từng request, giữ tên gốc trong metadata và cleanup theo lifetime worker; Role4 giữ regression test thay vì sửa file protected.")
p("<b>Timeout phải phản ánh hoạt động.</b> Upstream chuyển từ created_at sang last_activity để file đang tiến triển không bị coi như abandoned chỉ vì chạy lâu. Đây là thay đổi có ý nghĩa với file lớn. Tuy vậy, timeout nhận data và timeout chờ terminal result là hai state khác nhau; test mất FILE_RESULT cần thiết ngay cả khi24MiB không loss có thể hoàn tất.")
p("<b>Discovery chịu ảnh hưởng datagram loss/order.</b> Source/schema validation, seq và refresh giúp tránh dữ liệu cũ hoặc không hợp lệ làm hỏng peer map. Test phải kiểm convergence sau mất update cuối, không chỉ danh sách đúng ngay sau một login. Wraparound, server restart và source authentication mạnh hơn vẫn cần threat model/acceptance rõ.")
p("<b>Test xanh có thể trả lời sai câu hỏi.</b> Test cũ mất ACK cuối dừng khi vừa thấy done; worker có thể còn retry và ghi đè thành failed. Role4 đổi test để đợi chính worker kết thúc, xác minh fault thực sự xảy ra và byte-exact. Fixture file lớn từng làm hết disk; browser File cùngsize kiểm cùng validation mà không cần giả kích thước hoặc giảm yêu cầu.")
p("<b>Tách trách nhiệm giúp review được.</b> Browser không tự tạo ACK/retry/crypto mới. Mọi thay đổi ở đây nằm trong UI, test, demo và tài liệu Role4; network fixes được bàn giao với reproduction. Bài học cuối là ghi rõ điều chưa đạt trước khi bảo vệ: tích hợp streaming và congestion không được suy ra từ tên module hoặc số lượng test pass.")
story.append(PageBreak())
h("6. Readiness và bàn giao")
table([["Phạm vi", "Kết luận và việc cần làm"],["Demo cơ bản","Có thể trình diễn login/users/chat/file nhỏ và browser UI; dùng evidence thực. Không coi demo này là phê duyệt toàn đề."],["Toàn vẹn upload","Client owner cần staging per request; cùngbasename phải giữ nguyên bytes của từng người nhận."],["File terminal reliability","Role3 cần completion-result retry/ACK, terminal status bất biến và xử lý mất final ACK. Không được bỏ qua regression mới."],["Streaming/congestion","Role1/2 cần chốt transport với giảng viên, chứng minh runtime dùng byte stream async và mức BBR/CUBIC yêu cầu."],["Submission docs","PDF này có architecture/protocol/sequence/reflection. README riêng trong gói cung cấp startup; shared README vẫn cần owner duyệt cập nhật."],["Môi trường và giới hạn","Đĩa gần đầy; không tự xóa dữ liệu người dùng hoặc cài simulator nặng. Giải phóng/chuyển dữ liệu có chủ đích trước thử lớn hơn."]],[130,345])
p("<b>Identity/startup:</b> server chấp nhận username '*' nhưng client dùng '*' cho broadcast, khiến thông điệp định gửi riêng có thể tới người khác. TCP connect timeout không giới hạn HELLO/AUTH vì socket trở lại blocking trước khi đọc. Hai vấn đề có reproduction và handoff riêng.")
p("<b>Verdict:</b> chưa đủ bằng chứng để tuyên bố Assignment1 hoàn thành toàn bộ. Các lỗi còn lại có test/handoff riêng, không được biến thành expectedFailure để nộp suite xanh. Báo cáo cuối Markdown chứa status chi tiết của từng yêu cầu và kết quả backend/review mới nhất.")
p("<b>Thứ tự tiếp theo:</b> sửa integrity/terminal protocol trước; giữ UI hiển thị trung thực; rerun regression và fault tests; hoàn thiện phạm vi streaming/congestion; xác minh LAN và hồ sơ nộp. Assignment2 là dự án thiết kế hạ tầng riêng; chỉ tái dùng phương pháp evidence và workload A1 khi có lý do cụ thể, không dùng A1 thay topology/configurations.")
p("<b>Nguồn đối chiếu:</b> official Assignment1 PDF trang 1-4; Assignment1_Network_Application_Guide slide7,18,22,27; current protocol.py/client.py/server.py/file_client.py/file_transfer.py/udp_streamer.py; Git baseline3c41747; logs/JSON tại audits/finalization_2026_11_05. Tài liệu protocol cũ có thể lệch runtime; bảng ở báo cáo này mô tả code đã đọc.", "SmallVN")
def footer(c,doc):
    c.setStrokeColor(colors.HexColor("#cbd8dc")); c.line(45,42,550,42)
    c.setFont("Arial",8); c.setFillColor(navy)
    c.drawString(45,28,"Assignment 1 | Role 4 | Baseline 3c41747 | 05/11/2026")
    c.drawRightString(550,28,str(doc.page))
target=OUT/"Assignment1_Technical_Report.pdf"
SimpleDocTemplate(str(target),pagesize=(595.28,841.89),rightMargin=55,leftMargin=55,
    topMargin=45,bottomMargin=58,title="Assignment 1 - Technical Report",author="Role 4 - Client UI Testing").build(story,onFirstPage=footer,onLaterPages=footer)
print(target)
