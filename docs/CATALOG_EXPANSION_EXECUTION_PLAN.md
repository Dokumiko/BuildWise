# CATALOG_EXPANSION_EXECUTION_PLAN.md

**Loại tài liệu:** runbook vận hành nội bộ  
**Ngày cập nhật:** 2026-09-01  
**Phạm vi:** mở rộng catalog evidence-first cho BuildWise  
**Không phải:** đặc tả sản phẩm mới, thay đổi DDL, migration, hay thay đổi public API

## 1. Mục đích và nguyên tắc bất biến

Runbook này biến kế hoạch mở rộng catalog thành một quy trình có thể lặp lại, kiểm tra được và an toàn cho sandbox. Mục tiêu trước mắt là tăng độ phủ phục vụ kiểm thử compatibility và search, không phải tìm giá thấp nhất hoặc mô phỏng toàn bộ thị trường Việt Nam.

Các tài liệu frozen và hợp đồng hiện tại vẫn là authority cao hơn runbook này. Không sửa `docs/PROJECT_SPECIFICATION_v1.1.md`, `backend/data/database-schema-v0.1.sql`, Alembic baseline hoặc các intake contracts để làm cho một candidate vừa với pipeline.

Mọi fact phần cứng phải đến từ evidence giữ lại. Không suy luận giữa SKU/variant/revision/family; không fabricate giá, benchmark, provenance hoặc URL. Incompatible combinations được giữ lại làm input kiểm thử khi từng linh kiện đã được xác minh, không bị lọc ở ingestion.

## 2. Baseline và mục tiêu theo giai đoạn

Tại ngày 2026-09-01:

- Intake chính `vn-pc-am5-ddr5-v0.2` có 17 linh kiện: CPU 2, motherboard 2, RAM 2, GPU 2, PSU 2, storage 2, cooler 2, case 3 raw (canonical readiness vẫn áp dụng).
- Intake sandbox `vn-pc-am5-ddr5-sandbox` là nhánh phát triển riêng, hiện có 22 linh kiện với CPU mở rộng.
- Artifacts CPU hiện có các lớp technical, HACOM price observations/resolutions và PassMark candidates. Các artifact đã tồn tại phải được bảo toàn; không xoá hoặc ghi đè công việc PassMark.
- Lần chạy promotion deterministic ngày **2026-09-01** trên `cpu-benchmark-2026-08-29-expanded` có 67 identity CPU: 5 PASS toàn bộ gates (Ryzen 5 7500F; Ryzen 7 7700X; Ryzen 7 7800X3D; Ryzen 7 9700X; Ryzen 9 9900X), 62 được giữ lại với blocker. Intake kết quả `vn-pc-am5-ddr5-v0.3-cpu-evidence` có 22 components, 7 CPU và readiness constrained-search PASS; chưa được import vào database.

Milestone ban đầu: khoảng **15–25 canonical records/category**, ưu tiên diversity cho ma trận compatibility. Sau đó CPU/GPU có thể tăng lên khoảng 30–60 model khi evidence đủ. Một record chỉ được tính là “đã thêm” sau khi evidence gates, contract validation, readiness và sandbox persistence đều thành công.

## 3. Luồng thực thi chuẩn

```text
target registry
  -> robots/access check
  -> fetch raw artifacts + headers/metadata
  -> parse candidates
  -> exact identity/SKU join
  -> select one eligible VN retail price
  -> join direct CPU/GPU benchmark (nếu bắt buộc)
  -> Pydantic/intake validation
  -> coverage + promotion report
  -> versioned intake
  -> readiness
  -> sandbox import
  -> endpoint/compatibility smoke tests
```

Mỗi fetch phải giữ tối thiểu: requested URL, final URL, HTTP status, thời điểm retrieval, content type, byte count, content hash, raw response, parser output và lỗi. Robots, 403, anti-bot, TLS/network restriction hoặc redirect đáng ngờ là blocker; không bypass và không đổi sang nguồn không được quyết định.

Các tool trong `tools/catalog_ingestion/` chỉ là evidence tooling. Chúng không tự import PostgreSQL và không trở thành live retailer synchronization.

## 4. Evidence gates và trạng thái

### 4.1 Gates bắt buộc

| Gate | Điều kiện PASS |
|---|---|
| `identity` | component type, manufacturer, exact model và SKU/variant (khi áp dụng) thống nhất giữa candidate; không ambiguous redirect hoặc reused URL |
| `technical` | exact model từ nguồn kỹ thuật được giữ lại; fetch thành công; đủ raw fields của category; ưu tiên official manufacturer |
| `price` | đúng một listing retail Việt Nam, đúng exact SKU; một giá VND; mặc định HACOM; không bundle/open-box/OEM/tray cho policy boxed |
| `benchmark` | CPU có PassMark trực tiếp exact model; GPU có metric 3DMark theo intake contract, model association và limitation; nhóm khác không tạo benchmark giả |
| `contract` | payload candidate được chuyển qua Pydantic intake/component contract, không thiếu field, canonical aliases được normalize tại ingestion |
| `promotion` | chỉ PASS khi tất cả gate bắt buộc PASS và không duplicate/blocker |

`tools/catalog_ingestion/promotion_report.py` tạo coverage matrix/report deterministic từ các artifact arrays. Report có các cột `identity_gate`, `technical_gate`, `price_gate`, `benchmark_gate`, `contract_gate`, `base_intake_duplicate`, `blockers`, `promotion`. Contract validation phải được đưa vào artifact dưới dạng `contract_validations` (mỗi row có exact identity và `status: PASS`); thiếu row này **không** được hiểu là PASS.

### 4.2 Trạng thái không được promotion

`BLOCKED`, `AMBIGUOUS`, `INCOMPLETE`, thiếu evidence, thiếu price resolution, benchmark không exact, duplicate identity, source URL reused hoặc redirect sang model khác đều ở lại artifacts và unresolved report. Không tạo `APPROVED` giả để thỏa bridge cũ. Human review chỉ được dùng để cung cấp một resolution có audit trail; không thay thế technical/benchmark/contract gates.

### 4.3 Chính sách giá

- Mỗi linh kiện chỉ dùng một giá bán lẻ Việt Nam trong intake được phát hành.
- CPU ưu tiên **retail boxed/sealed**; tray/OEM chỉ là unresolved đối với promotion boxed.
- Các nhóm khác phải là đúng SKU bán lẻ nguyên hộp; loại open-box, bundle hoặc SKU không xác định bị loại.
- `price_resolutions` là operator-authored evidence join, không được tính bằng min/max/cheapest tự động.
- Listing URL phải là URL raw HTTP(S), giữ provenance; kiểm tra URL ownership trước import.

## 5. Yêu cầu dữ liệu theo category

### CPU

Cổng kỹ thuật: socket, CPU family, cores, threads, TDP, memory type, integrated graphics, PCIe version. Cổng benchmark: PassMark CPU Mark trực tiếp, title/canonical URL/on-page identity/CPU ID phải trùng exact model. Ryzen 9 7900X vẫn blocked nếu thiếu PCIe evidence.

### GPU/VGA

Giữ exact board SKU, chiều dài, slot width, VRAM, total graphics power, power connectors, PCIe generation/lanes và model association. Benchmark 3DMark chỉ là model-level proxy nếu intake contract yêu cầu; luôn giữ `match_scope`, `exact_board_sku_verified=false` và limitation.

### Motherboard

Socket, supported CPU families, form factor, DDR generation/capacity/slots/speed limits, M.2 topology, SATA ports và power connectors. Optional connector không được nâng thành requirement nếu nguồn không nói vậy.

### RAM

Exact kit SKU, DDR generation, total capacity, module count, capacity/module, SPD/tested speed, voltage, XMP/EXPO. Chỉ ghi chiều cao khi nguồn công bố rõ.

### Storage

Exact capacity SKU, interface, form factor, capacity, PCIe generation/lanes và các power fields mà contract hiện yêu cầu. Không tạo power observation từ model family.

### PSU

Form factor, wattage, connector counts, ATX/PCIe version. Normalize `12VHPWR` thành `12V_2X6` một lần tại ingestion; canonical payload không giữ alias.

### Case

Supported motherboard/PSU form factors, GPU length context, cooler height, PSU length, slot-width limit nếu có, radiator positions/sizes và clearance conditions. Nếu radiator/clearance còn conditional, giữ raw-only.

### Cooler

Supported sockets, air/AIO type, height hoặc radiator size, RAM clearance khi công bố và fan/pump input power theo contract. Không lấy giá trị từ cooler family gần giống.

## 6. Trình tự milestone

1. **CPU coverage:** hoàn tất matrix từ artifacts hiện có; chỉ promotion CPU đủ technical + boxed price + direct PassMark + contract. Recompute CPU benchmark bounds sau khi tập model thay đổi.
2. **Motherboard + RAM:** mở rộng AM4/AM5, DDR4/DDR5, ATX/Micro-ATX/Mini-ITX để tạo compatibility matrix.
3. **GPU + PSU + case:** bổ sung GPU ngắn/dài, 2–4 slot, connector/power tiers; PSU 550/650/750/850/1000W; case có clearance tương phản.
4. **Cooler:** air thấp/cao và AIO 240/280/360, nhiều socket.
5. **Storage:** SATA và NVMe, nhiều dung lượng, form factor và PCIe Gen 3/4/5.
6. Khi mỗi category đạt 15–25 records, đo coverage và bổ sung theo gap của ma trận, không chỉ tăng count.
7. Chỉ sau catalog đủ lớn mới phục hồi bulk review và đánh giá thesis-scale.

Mỗi milestone cho phép promotion theo một component/micro-batch; không cần chờ toàn bộ category.

## 7. Checklist cho mỗi component/micro-batch

### Trước fetch

- [ ] Target registry có exact model/SKU, category, expected variant và URL đã xác minh.
- [ ] Xác định database đích là sandbox; không cần DB cho crawler.
- [ ] Kiểm tra robots/access cho từng origin; đặt delay/timeouts bounded.

### Sau fetch/parse

- [ ] Raw response, headers, metadata, hash và parser output đã lưu.
- [ ] Final URL/status/content type hợp lệ; không có suspicious redirect.
- [ ] Exact identity/SKU join không ambiguous.
- [ ] Technical fields là source-observed; thiếu field để unresolved.
- [ ] Price listing là một retail boxed listing HACOM hoặc blocker chính xác.
- [ ] CPU/GPU benchmark trực tiếp và đúng match scope; category khác không có benchmark giả.
- [ ] Không trùng component với intake gốc hoặc records đã promotion.

### Trước promotion

- [ ] Chạy parser/unit tests.
- [ ] Validate candidate và versioned intake bằng Pydantic.
- [ ] Kiểm tra URL ownership, provenance joins và duplicate identity.
- [ ] Chạy `promotion_report.py`; chỉ lấy rows `promotion: true`.
- [ ] Sinh `unresolved/blocker report`; không xoá blocker.
- [ ] Recompute benchmark bounds cho CPU/GPU.

### Trước và sau sandbox import

- [ ] Xác minh chính xác `DATABASE_URL`/database name là sandbox.
- [ ] DB sạch đã áp dụng approved DDL và `alembic stamp 0001_schema_v01` nếu cần.
- [ ] `check_catalog_readiness` trả `READY`/`constrained_search_ready` theo contract.
- [ ] Import transaction vào sandbox, không main DB.
- [ ] Kiểm tra `GET /api/v1/catalog-datasets`, component endpoint và counts.
- [ ] Smoke-test một build hợp lệ, một build không hợp lệ và recommendation endpoint.
- [ ] Ghi compatibility coverage matrix và kết quả deterministic request.

## 8. Lệnh vận hành tham chiếu

Từ repository root:

```powershell
# Unit/parser tests (sử dụng interpreter môi trường backend đã cài dependencies)
& .\backend\.venv\Scripts\pytest.exe tools\catalog_ingestion\tests backend\tests -q

# Coverage report; không ghi database
python tools/catalog_ingestion/promotion_report.py `
  --candidates tools/catalog_ingestion/runs/<run>/cpu-candidates-merged.json `
  --base-intake backend/data/vn-pc-am5-ddr5-v0.2-catalog-evaluation-intake.json `
  --contract-validations tools/catalog_ingestion/runs/<run>/contract-validations.json `
  --output tools/catalog_ingestion/runs/<run>/coverage-matrix.json

# Readiness (chạy trong backend)
cd backend
python -m app.scripts.check_catalog_readiness --path data\<versioned-intake>.json
python -m app.scripts.import_evaluation_intake --path data\<versioned-intake>.json
```

`promotion_report.py` không tạo intake và không import. Với CPU, `promote_cpu_candidates.py` là bridge automatic đầu tiên: nó sinh `contract-validations.json`, coverage matrix và unresolved report; chỉ khi tất cả gates PASS nó mới có thể viết một intake version mới, sau đó validate intake/readiness. Category khác cần bridge riêng với raw fields/provenance tương ứng; artifact report chỉ là eligibility evidence, không phải oracle.

## 9. Negative tests bắt buộc

Mỗi pipeline/category phải có test cho: sai SKU; ambiguous variant; thiếu required field; tray-only CPU; reused/ambiguous URL; thiếu CPU/GPU benchmark; connector alias không canonical; clearance thiếu context; redirect sang model khác; HTTP 403/robots disallow; source final URL/status không hợp lệ; duplicate với intake base.

Test phải chứng minh candidate bị giữ lại ở blocker/unresolved artifact và raw evidence không bị mutate. Không dùng expected benchmark/price hard-code nếu không có artifact nguồn tương ứng.

## 10. Tiêu chí hoàn thành và audit trail

Một micro-batch hoàn thành khi:

1. Từng record có evidence identity, technical, giá và benchmark theo category.
2. Pydantic/intake validation PASS, provenance joins và duplicate checks PASS.
3. Readiness report không còn blocker liên quan records được promotion.
4. Sandbox persistence thành công và idempotency/count checks PASS.
5. API smoke tests và compatibility coverage được ghi lại.

Nếu bước nào thất bại, không rollback artifacts evidence; giữ raw/candidate/report và ghi blocker cụ thể để xử lý lần sau. Không commit/push/import main database trong runbook này. Live retailer sync, auth, what-if, comparison và Phase 4 LLM vẫn deferred.
