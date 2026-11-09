"""Build the release PDF from executed evidence. Optional requirements-report.txt."""
from pathlib import Path
from html import escape
import json
import hashlib
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Flowable
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT/'audits/release_2026_11_07'
OUT = ROOT/'output/pdf/Assignment1_Release_Report.pdf'
for regular, bold in [('C:/Windows/Fonts/arial.ttf','C:/Windows/Fonts/arialbd.ttf'),
                      ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                       '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')]:
    if Path(regular).exists() and Path(bold).exists():
        pdfmetrics.registerFont(TTFont('VN',regular)); pdfmetrics.registerFont(TTFont('VNB',bold))
        break
else:
    raise RuntimeError('Install Arial or DejaVu Sans with Vietnamese glyphs to build the PDF')
pdfmetrics.registerFontFamily('VN',normal='VN',bold='VNB',italic='VN',boldItalic='VNB')
styles=getSampleStyleSheet()
for s in styles.byName.values(): s.fontName='VN'
styles.add(ParagraphStyle(name='BodyVN',fontName='VN',fontSize=10,leading=15,spaceAfter=9))
styles.add(ParagraphStyle(name='SmallVN',fontName='VN',fontSize=8.3,leading=11.5,spaceAfter=5))
for n in ('Title','Heading1','Heading2'):
    styles[n].fontName='VNB'; styles[n].textColor=colors.HexColor('#16384a')
styles['Title'].fontSize=24; styles['Title'].leading=31
styles['Heading1'].fontSize=17; styles['Heading1'].leading=23
styles['Heading2'].fontSize=12; styles['Heading2'].leading=17
story=[]
def p(text,style='BodyVN'): story.append(Paragraph(text,styles[style]))
def h(text): p(text,'Heading1')
def page(): story.append(PageBreak())
def table(rows,widths=(130,345)):
    data=[[Paragraph(escape(str(c)),styles['SmallVN']) for c in row] for row in rows]
    t=Table(data,colWidths=widths,hAlign='LEFT',repeatRows=1)
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e3ecee')),
        ('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),7),
        ('BOTTOMPADDING',(0,0),(-1,-1),7),('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#ccd8dc'))]))
    story.extend([t,Spacer(1,12)])

class Architecture(Flowable):
    def __init__(self):
        super().__init__()
        self.width=475; self.height=184
    def draw(self):
        c=self.canv
        boxes=[(0,134,145,36,'Browser JavaScript'),(185,134,290,36,'HTTP bridge + CollaborationClient'),
               (185,68,290,36,'TCP server: registry + chat routing'),
               (0,0,475,38,'Peer UDP: file protocol + OrderedByteStream + CubicWindow')]
        c.setFont('VN',9)
        for x,y,w,hh,label in boxes:
            c.setFillColor(colors.HexColor('#eef4f5')); c.setStrokeColor(colors.HexColor('#08695e'))
            c.roundRect(x,y,w,hh,5,fill=1); c.setFillColor(colors.HexColor('#16384a'))
            c.drawCentredString(x+w/2,y+hh/2-3,label)
        c.line(145,152,185,152); c.line(330,134,330,104)
        c.line(160,152,160,38); c.line(160,152,185,152)
        c.setFont('VN',8); c.drawString(335,118,'TCP control/chat; UDP discovery')
        c.drawString(3,91,'GET state / POST send,file')

class Sequence(Flowable):
    def __init__(self,actors,steps):
        super().__init__(); self.actors=actors; self.steps=steps
        self.width=475; self.height=50+35*len(steps)
    def draw(self):
        c=self.canv; xs=[35+i*405/(len(self.actors)-1) for i in range(len(self.actors))]
        top=self.height-12
        for x,name in zip(xs,self.actors):
            c.setFont('VNB',9); c.drawCentredString(x,top,name)
            c.setDash(2,3); c.setStrokeColor(colors.HexColor('#bbcbd2')); c.line(x,top-8,x,4); c.setDash()
        for i,(a,b,label) in enumerate(self.steps):
            y=top-35-i*35; x1,x2=xs[a],xs[b]; sign=1 if x2>x1 else -1
            c.setStrokeColor(colors.HexColor('#08695e')); c.line(x1,y,x2,y)
            c.line(x2,y,x2-sign*5,y+3); c.line(x2,y,x2-sign*5,y-3)
            c.setFont('VN',8); c.drawCentredString((x1+x2)/2,y+6,label)

def evidence(name): return json.loads((EVIDENCE/name).read_text(encoding='utf-8-sig'))
runs=[evidence('final_run_1.json'),evidence('final_run_2.json')]
large=evidence('maximum_file.json'); probes=evidence('protocol/results.json'); legacy=evidence('legacy.json')
assert all(r['status']=='PASS' for r in runs), 'Do not publish a green report over failed release suites'
assert runs[0]['source_sha256']==runs[1]['source_sha256'], 'Runs must cover the same implementation'
fingerprint=hashlib.sha256(json.dumps(runs[0]['source_sha256'],sort_keys=True).encode()).hexdigest()

p('NETWORK APPLICATION DEVELOPMENT','Heading2')
p('Assignment 1<br/>Release Closure','Title')
p('Báo cáo kỹ thuật và bằng chứng kiểm chứng | 07/11/2026','Heading2')
p('<b>Kết luận kỹ thuật:</b> các lỗi tái hiện trong phạm vi release đã được sửa và kiểm thử lại. '
  'Sẵn sàng trình diễn localhost Windows với các giới hạn nêu rõ. <b>Đánh giá toàn đề: PARTIAL</b> '
  'cho đến khi giảng viên xác nhận cách hiểu transport cho streaming chat; chưa chứng minh LAN nhiều máy hay fairness WAN.')
story.append(Architecture())
story.append(Spacer(1,10))
p('<b>Thiết kế:</b> HTTP chuẩn thư viện phục vụ một trang HTML/JavaScript; browser chỉ gọi API cục bộ. '
  'TCP đảm nhiệm handshake, đăng nhập tên duy nhất và routing chat. UDP đảm nhiệm heartbeat, discovery '
  'và file trực tiếp giữa peer. Bộ nhận byte bất đồng bộ tách khỏi JSON, mã hóa và filesystem.')
p(f'<b>Bằng chứng chính:</b> hai lượt suite cùng source, mỗi lượt {runs[0]["counts"]["tests"]} test thực; '
  f'file 100 MiB với SHA-256 khớp trong {large["seconds"]} giây; 20 client đồng thời; browser thật; '
  'fault injection trên datagram thật. Không quy đổi subtest, expected failure hay observation thành test PASS.')
p('Baseline team: 3c4174791a7e796a18e6d57c98c03111359cc1a5.<br/>'
  'Worktree: release/assignment1-closure-2026-11-05. Thay đổi các role được phép riêng cho release; không push/merge.','SmallVN')
p('Fingerprint tập source/test đã chạy: '+fingerprint,'SmallVN')
page()
h('1. Protocol và ranh giới trạng thái')
table([['Trường header','Wire contract'],['magic (uint16)','0xDCBA'],['type / status (uint8 mỗi trường)','HELLO 01/02, AUTH 03/04, LOGOUT 05/06; HEARTBEAT10, USER_LIST11, EOF12, DATA20, ACK21 (hex). Status0/1/2: none/ok/error.'],
       ['seq / payload_len (uint16 mỗi trường)','Big-endian !HBBHH, header8byte; payload tối đa65535byte. TCP đọc đủ frame, UDP yêu cầu đúng độ dài.'],
       ['Sequence','Header quay vòng16bit. File dùng UUID + logical chunk_index nên không nhầm ACK khi header quay vòng. Standalone UDP stream chỉ dùng endpoint mới và <=65535 data chunks.']])
p('<b>Phiên:</b> HELLO → AUTH(username, udp_port) → AUTH_RESP(session_id). Server lưu tên, IP, '
  'UDP port và socket. Tên phải hợp lệ và duy nhất. Logout kiểm token phiên. Tham số password '
  'được giữ tương thích nhưng không có kho tài khoản hoặc xác minh mật khẩu.')
p('<b>File:</b> FILE_META gồm file_id, filename, size, sha256, chunk_size và total_chunks; '
  'FILE_CHUNK mang chunk_index và dữ liệu base64. JSON được Fernet bảo vệ. ACK xác nhận chunk, '
  'không xác nhận toàn file. FILE_RESULT completed chỉ sau hash, ghi và publish thành công; '
  'FILE_QUERY truy vấn lại kết quả đã lưu trong cache giới hạn.')
p('<b>State/API:</b> GET /api/state trả username, users dạng object, messages, transfers, connection và operations. '
  'POST /api/send và /api/file trả ok nghĩa là đã nhận công việc. Lỗi worker xuất hiện qua operations; '
  'transfer phải tự đạt done/completed. API sống không đồng nghĩa server sống; disconnected xóa peers, '
  'API mất kết nối làm UI bỏ xác nhận server và giữ draft.')
p('<b>Giới hạn:</b> file layer100MiB; HTTP body110MiB nên upload browser khoảng82,5MiB vì base64/JSON. '
  '8 transfer gửi và8 nhận mỗi client; metadata/chunk/terminal record có giới hạn. CUBIC cap64, '
  'ngưỡng slow-start8; retry0,5s, tối đa5 lần. Receiver idle120s; terminal cache256/120s.','SmallVN')
page()
h('2. Vòng đời message và file')
p('Message được gửi thành công đến local bridge chưa phải bằng chứng người nhận đã đọc hoặc nhận được.','SmallVN')
story.append(Sequence(['Browser A','Client A','Server','Client B'],[
    (0,1,'POST /api/send; nhận công việc'),(1,2,'TCP DATA: mode, recipient, encrypted text'),
    (2,3,'Queue riêng mỗi peer; forward/broadcast'),(1,0,'Polling: message / operation error')]))
p('File: quyết định hoàn tất thuộc receiver đã kiểm chứng, không thuộc ACK chunk cuối.','SmallVN')
story.append(Sequence(['Sender','Receiver'],[
    (0,1,'FILE_META; receiver kiểm schema / dung lượng'),(1,0,'ACK index=-1'),
    (0,1,'FILE_CHUNK: cửa sổ CUBIC, retry riêng chunk mất'),(1,0,'ACK chunk được nhận hợp lệ'),
    (1,0,'Sau SHA-256 + atomic publish: FILE_RESULT'),(0,1,'Nếu kết quả mất: FILE_QUERY / retransmit'),
    (1,0,'Replay terminal result; sender chuyển done')]))
page()
h('3. Kết quả chạy và khả năng tái lập')
table([['Phép thử','Kết quả thực tế'],
       ['Full suite lần1',f"{runs[0]['counts']['passed']}/{runs[0]['counts']['tests']} PASS; {runs[0]['seconds']}s; 0fail/error/skip"],
       ['Full suite lần2 (venv mới)',f"{runs[1]['counts']['passed']}/{runs[1]['counts']['tests']} PASS; {runs[1]['seconds']}s; source fingerprint khớp"],
       ['Protocol probes',f"{probes['passed']}PASS, {probes['failed']}FAIL, {probes['observations']}observation; {probes['duration_s']}s"],
       ['Legacy scripts', '; '.join(f"{Path(r['command'][-1]).name}: {r['pass_groups']}/{r['expected_groups']} nhóm {r['status']}" for r in legacy)],
       ['Maximum file',f"{large['bytes']}byte;149797chunks; {large['seconds']}s; senderdone / receivercompleted; pendingACK0; chat tiếp tục"],
       ['Môi trường','Windows / Python3.14.4 / cryptography50.0.2 / pytest9.2.0 / Playwright1.55.0 + Microsoft Edge.']])
p('<b>Không che thất bại:</b> baseline_reproduction.txt lưu3 lỗi gốc. full_run_1.txt là lượt điều tra '
  '85 test:82 đạt,3 lỗi. Hai lỗi mới là cleanup socket đã đóng và race trong fixture. Lỗi UI là transfer '
  'nhanh hơn polling; phép thử mới giữ một chunk đến khi browser thấy progress thực rồi giải phóng, vẫn kiểm hash '
  'và hai trạng thái terminal. Bằng chứng HTTP origin và CUBIC trước/sau sửa được giữ riêng.')
p('Lệnh chính: python scripts/verify_release.py --label final_run_1<br/>'
  'python scripts/verify_release.py --label final_run_2<br/>'
  'python scripts/verify_large_release.py --mib 100 --output test-results/maximum.json<br/>'
  'python scripts/verify_protocol_release.py<br/>python scripts/verify_legacy_release.py','SmallVN')
p('Các file JSON/XML/TXT trong audits/release_2026_11_07 là nguồn số liệu. JSON final_run ghi interpreter, '
  'command, thời gian, source hashes và kết quả kiểm source không đổi trong khi chạy. '
  'Chạy nối tiếp để không xung đột cổng9000/9001; harness từ chối cổng bận và dọn process do chính nó tạo.')
p('Sau hai lượt suite, chỉ harness test_udp_streaming.py được sửa: receiver phải còn nghe để ACK '
  'retransmit sau khi ghép đủ bytes. Tỷ lệ loss, retry và assertion không đổi; script legacy được '
  'chạy lại riêng. Production và 90 test methods trong suite không đổi. Xem legacy_before_legacy.json '
  'và legacy.json để đối chiếu.','SmallVN')
page()
h('4. Challenges &amp; Solutions')
p('Phản ánh kỹ thuật - một trang','Heading2')
p('<b>Kết quả cuối bị mất.</b> Mất ACK hoặc FILE_RESULT là lỗi khác với mất dữ liệu. Receiver có thể đã '
  'ghi file đúng trong khi sender hết retry. Giải pháp giữ terminal result có peer/UUID/hash/size, trả lại '
  'khi nhận query hoặc retransmit; sender chỉ nhận kết quả từ peer dự kiến. Nếu mọi kết quả đều mất, '
  'sender ghi completion unconfirmed, không bịa thành công hay đảo kết quả đã xác minh.')
p('<b>Upload cùng tên và publish an toàn.</b> Hai HTTP request từng dùng chung staging path dẫn tới đọc '
  'nhầm nội dung. Mỗi request nay có thư mục tạm riêng, cleanup sau snapshot. Receiver ghi .part, fsync '
  'và hard-link publish không overwrite. Kiểm tra tạo file đích muộn chứng minh không thay thế dữ liệu cũ; '
  'hệ thống file phải hỗ trợ hard link.')
p('<b>Streaming và độc lập giữa các luồng.</b> OrderedByteStream cấp read() bất đồng bộ trên byte liên tục '
  'trước EOF, giới hạn buffer, dọn waiter khi cancel. Mỗi transfer có worker/window riêng; thử mất chunk '
  'ở file lớn đồng thời file nhỏ và chat vẫn tiến triển. Byte trước hash là provisional. Reassembly '
  'vẫn giữ chunk trong RAM; không quảng cáo constant-memory streaming hoặc loại bỏ HoL của TCP chat.')
p('<b>ACK, congestion và socket lỗi.</b> ACK mới hợp lệ mới tăng cwnd; mất gói giảm cửa sổ và retry riêng '
  'chunk còn thiếu. Tách cap64 khỏi threshold8 để thực sự vào congestion avoidance. ACK sai peer/format '
  'bị bỏ qua; socket đã đóng không gây exception ở cleanup. CUBIC là controller giới hạn cho lab, '
  'không tương đương một stack TCP/QUIC đã kiểm chứng fairness Internet.')
p('<b>Client chậm và trạng thái UI.</b> Queue riêng giới hạn giúp slow reader không chặn người khỏe; '
  'handshake dùng tổng deadline, không bị kéo dài vô hạn bởi frame từng phần. Operations đưa lỗi worker '
  'lên HTTP; connection phản ánh phản hồi server. Origin/Host/Content-Type chặn trang ngoài điều khiển '
  'bridge. Mọi dữ liệu UI không tin cậy dùng safe DOM; lỗi polling giữ draft và bỏ xác nhận server.')
page()
h('5. Ma trận yêu cầu và mức sẵn sàng')
table([['Yêu cầu trong đề','Bằng chứng / trạng thái'],
       ['1 Protocol design','Header, opcode, state và sequence được tài liệu hóa; không chứng minh được yêu cầu tài liệu phải có trước mọi dòng code trong lịch sử.'],
       ['2 TCP handshake','Framing, partial HELLO, silent AUTH, tổng deadline: đã kiểm.'],
       ['3 Login / registry','Tên duy nhất, IP/port, session/logout và invalid port: đã kiểm. Password authentication không được triển khai.'],
       ['4 Concurrency 10-20','20 client broadcast, crash isolation, login lại và slow reader: đã kiểm localhost.'],
       ['5 Routing / streaming','Broadcast/private TCP đã kiểm. Async UDP bytes và file song song đã kiểm. Cần giảng viên xác nhận mục tiêu UDP streaming chat có bắt buộc hay không.'],
       ['6 UDP file','Empty/binary/Unicode/multiple/100 MiB, hash, chunk loss/reorder/duplicate, final ACK/result loss: đã kiểm.'],
       ['7 Resilience','Heartbeat Windows, sudden disconnect, server stop, interrupted transfer, explicit failure, manual new session: đã kiểm. Không tự reconnect/resume file.'],
       ['8 Payload security','Fernet chat/file, tamper/schema checks, safe filenames, HTTP origin gate. Shared demo key; metadata không TLS, không phải end-to-end identity security.'],
       ['9 HTTP + JavaScript UI','client.main thật, hai browser chat/file, user list, progress, API failure, XSS và mobile layout: đã kiểm.'],
       ['10 Test / code quality','Hai full suite không skip/xfail; source hash; raw sockets; không Flask/Django/WebSockets; demo/ZIP verifier có thể chạy lại.']],(119,356))
page()
h('6. Bàn giao và phần chưa chứng minh')
p('<b>PASS về các phép thử đã thực thi; PARTIAL về xác nhận toàn bộ đề.</b> Không còn blocker tái hiện '
  'trong các luồng được kiểm. Tuy nhiên không dùng kết quả localhost để suy ra mọi mạng, mọi hệ điều hành '
  'hoặc mọi cách chấm đề đều đạt.')
table([['Ưu tiên','Việc còn lại / điều kiện'],
       ['P0 trước khi chốt rubric','Hỏi giảng viên: mục tiêu UDP STREAMING có yêu cầu chat cũng chạy UDP không, dù mục kỹ thuật nói TCP message và milestone 5 chỉ yêu cầu routing? Nếu có, cần thiết kế reliable UDP chat và test độc lập; chưa triển khai trong release này.'],
       ['P1 trình diễn LAN','Hai máy riêng, cấu hình server bind TCP/UDP, firewall, cùng key, địa chỉ LAN; chạy chat/file/hash và ngắt mạng. Chưa thực thi trên môi trường này.'],
       ['P1 trust/security','Chỉ demo mạng tin cậy. Key mặc định nằm trong source; peer có key có thể giả payload. Chưa có tài khoản, TLS, trao đổi key, authenticated discovery hay chống replay toàn diện.'],
       ['P2 tài nguyên','Full file trong RAM, 8 send + 8 receive tối đa có overhead đáng kể; browser JSON buffer. Chưa benchmark fairness WAN, memory pressure dài hạn, Linux/macOS hay FAT/exFAT.'],
       ['P2 recovery','Server restart cần khởi động client mới. Transfer thất bại cần gửi lại; không persist/resume. Terminal cache hữu hạn nên mất kết quả quá lâu phải báo unconfirmed.']])
p('<b>Demo tự động:</b> python submission/assignment1/demo.py mở server và hai client thật; '
  'nhấn Enter đóng process do demo tạo. Có thể chạy thủ công tại ba terminal:')
p('python server.py<br/>python client.py --username alice --host 127.0.0.1 --ui-port 8000<br/>'
  'python client.py --username bob --host 127.0.0.1 --ui-port 8001','SmallVN')
p('<b>Gói nộp:</b> source, tests, README, protocol, reportPDF và evidence hiện hành; MANIFEST.json '
  'hash từng file. Verifier giải nén sang thư mục tạm và chạy chat/file SHA-256 qua runtime thật. '
  'Commit đóng gói nằm trong manifest; không push, không merge tự động.')
p('<b>Nguồn:</b> Assignment 1 official PDF trang 1-4 (yêu cầu, 10 milestones, nội dung nộp); '
  'guide trong workspace; source và logs release. Công thức CUBIC tham khảo RFC 9438 §§4.2-4.8 '
  '(https://www.rfc-editor.org/rfc/rfc9438.html). Bản này không tuyên bố full RFC conformance.','SmallVN')

def footer(c,doc):
    c.setStrokeColor(colors.HexColor('#d4dfe3')); c.line(58,43,537,43)
    c.setFont('VN',8); c.setFillColor(colors.HexColor('#536b77'))
    c.drawString(58,29,'Assignment 1 | Release verification | 07/11/2026')
    c.drawRightString(537,29,str(doc.page))
OUT.parent.mkdir(parents=True,exist_ok=True)
SimpleDocTemplate(str(OUT),pagesize=(595.28,841.89),leftMargin=60,rightMargin=60,
                  topMargin=48,bottomMargin=58,title='Assignment 1 - Release Closure',
                  author='Project team / Release verification').build(story,onFirstPage=footer,onLaterPages=footer)
print(OUT)
