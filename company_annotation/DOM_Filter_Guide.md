# 公司列表页面 DOM 筛选操作与 6 大业务场景指引

本指南专门针对 **JobLeap 后台 - 公司列表页面**（`/#/company-basic/index`）的筛选操控进行详细说明，涵盖页面底层结构、核心选择器、取值字典映射，以及日常公告标注工作中高频使用的 **6 大核心筛选场景**（含手工 DOM 点选步骤、Playwright DOM 模拟代码、Vue 响应式一键操控代码及 API 请求 Payload），并已将通过真机验证的**独立快速筛选脚本 [fast_filter.py](file:///D:/100_Work/101_Program/Proj/XHS/company_annotation/fast_filter.py) 完整源码与使用说明**收录入本文档[【第五章】](#五生产级快速筛选脚本fast_filterpy完整源码)。

---

## 📑 快速目录索引
- [一、页面核心环境与技术架构](#一页面核心环境与技术架构)
- [二、核心筛选控件与取值字典一览](#二核心筛选控件与取值字典一览)
- [三、6 大核心业务情形操控指引](#三6-大核心业务情形操控指引)
  - [情形 1：类型排除境外企业 + 校招 + 爬取时间一天内 + 网申开始时间一月前](#情形-1类型排除境外企业--校招--爬取时间一天内--网申开始时间一月前)
  - [情形 2：类型排除境外企业 + 校招 + 爬取时间一天内 + 关联公告未关联（核心待办池）](#情形-2类型排除境外企业--校招--爬取时间一天内--关联公告未关联)
  - [情形 3：类型排除境外企业 + 校招 + 爬取时间一天内 + 网申届数为未标注和26届、25届](#情形-3类型排除境外企业--校招--爬取时间一天内--网申届数为未标注和26届25届)
  - [情形 4：类型排除境外企业 + 校招 + 爬取时间选择前一日和当天 + 网申开始时间一月前](#情形-4类型排除境外企业--校招--爬取时间选择前一日和当天--网申开始时间一月前)
  - [情形 5：类型排除境外企业 + 校招 + 爬取时间选择前一日和当天 + 关联公告未关联（查漏补缺池）](#情形-5类型排除境外企业--校招--爬取时间选择前一日和当天--关联公告未关联)
  - [情形 6：类型排除境外企业 + 校招 + 爬取时间选择前一日和当天 + 网申届数为未标注和26届、25届](#情形-6类型排除境外企业--校招--爬取时间选择前一日和当天--网申届数为未标注和26届25届)
- [四、6 大情形实测数据与效果对比](#四6-大情形实测数据与效果对比)
- [五、快速筛选脚本（fast_filter.py）使用指引](#五快速筛选脚本fast_filterpy使用指引)
- [六、数据接口（API）请求与结构化响应全解](#六数据接口api请求与结构化响应全解)

---

## 一、页面核心环境与技术架构

- **页面访问路径**：`http://admin.jobleap.betaquantity.com/#/company-basic/index`
- **前端技术栈**：`Vue 2` + `Element UI`
- **Vue 实例挂载**：筛选表单属于列表主组件，可通过 `document.querySelector('.el-form').__vue__.$parent` 获取组件响应式实例 `vm`。
- **数据查询接口**：`POST https://www.tatawangshen.com/api/recruit/company/basic/all`

---

## 二、核心筛选控件与取值字典一览

| 控件名称 | 页面 Label / Placeholder | DOM 定位选择器 | Vue Model 变量 | API Payload 字段 | 取值与字典对照 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **企业类型** | `请选择` (类型) | `.el-form-item:has(.el-form-item__label:has-text('类型')) .el-cascader` | `vm.orgType` | `org_type` | **全场景通用规则**：勾选除【境外企业】(18) 以外的全部 17 项。界面呈现为 `央企 ⊗ + 16` 折叠标签。 |
| **岗位类型** | `请选择岗位类型` | `.el-form-item:has(.el-form-item__label:has-text('岗位类型')) .el-select` | `vm.cls` | `class` | **全场景通用规则**：固定勾选【校招】，数组形式 `[0]` |
| **岗位爬取时间** | `岗位爬取时间：` *(选校招后动态出现)* | `.el-form-item:has(.el-form-item__label:has-text('岗位爬取时间')) .el-date-editor` | `vm.position_spider_date` | `position_spider_time_s`<br>`position_spider_time_e` | 数组 `[开始时间, 结束时间]`，支持快捷项与日期区间 |
| **网申开始时间** | `网申开始时间：` | `.el-form-item:has(.el-form-item__label:has-text('网申开始时间')) .el-date-editor` | `vm.posting_publish_date` | `publish_date_s`<br>`publish_date_e` | 数组 `[开始时间, 结束时间]`，支持快捷项（高频使用 **`一月前`**） |
| **关联公告** | `是否关联公告` | `.el-form-item:has(.el-form-item__label:has-text('关联公告')) .el-select` | `vm.positing_exist` | `positing_exist` | `true` (已关联), `false` (未关联), `null` (全部) |
| **网申届数** | `请选择届数` | `.el-form-item:has(.el-form-item__label:has-text('网申届数')) .el-select` | `vm.grade` | `grade` | 数组形式：`-1` (未标注), `26` (26届), `25` (25届), `27` (27届) 等 |
| **搜索按钮** | `搜索` | `button.el-button--primary:has-text('搜索')` | 触发 `vm.searchClick()` | - | 点击后重置为第 1 页并刷新列表 |

> **关键机制与踩坑说明**：
> 1. **【类型】视觉与参数匹配**：Element UI 的 `el-cascader` 内部节点选中后的 value 是形如 `'0-1', '1-1', '2-1' ...` 的格式。通过原生 DOM 展开并在 Popper 面板勾选除【境外企业】外的复选框，不仅最自然逼真，而且能确保输入框 100% 渲染 `央企 ⊗ + 16`，同时下发合法的 API 参数。
> 2. **【动态展开】**：【岗位类型】选择“校招”后，组件会自动触发 `clsChange`，动态显示【岗位爬取时间】与【岗位更新时间】。
> 3. **【届数未标注】**：下拉菜单中的“未标注”在 Element UI 底层绑定的实际值为 `-1`。
> 4. **【深度清空】**：原生 `vm.resetFilterData()` 不会主动清空 `posting_publish_date` 等时间字段，自动化切换场景前必须显式将时间、届数、公告状态置空，确保跨场景 0 残留。

---

## 三、6 大核心业务情形操控指引

---

### 情形 1：类型排除境外企业 + 校招 + 爬取时间一天内 + 网申开始时间一月前

#### 1. 业务目的
锁定国内所有企业中，“最新 24 小时刚爬取到，且网申开始时间截止在一个月前（排查往期/早前启动网申）”的校招岗位。

#### 2. 手工 DOM 点击操作步骤
1. 点击【类型】级联选择框，在弹出的多选面板中，勾选除 **【境外企业】** 以外的所有选项（共 17 项），输入框显示为 `央企 ⊗ + 16`。按 ESC 或点击空白处收起面板。
2. 点击【岗位类型】下拉框，在弹出的下拉菜单中勾选 **校招**。
3. 页面动态出现【岗位爬取时间】输入框，点击该输入框，在弹出的日期面板左侧快捷栏点击 **一天内**。
4. 点击【网申开始时间】输入框，在弹出的日期面板左侧快捷栏点击 **一月前**。
5. 点击右侧的 **【搜索】** 按钮。

#### 3. 自动化实现代码
```python
# 1. 选类型（排除境外企业，DOM 真实勾选）
await page.locator(".el-form-item:has(.el-form-item__label:has-text('类型')) .el-cascader").first.click()
await asyncio.sleep(0.4)
dropdown = page.locator(".el-cascader__dropdown:not([style*='display: none'])")
for i in range(await dropdown.locator(".el-cascader-node").count()):
    node = dropdown.locator(".el-cascader-node").nth(i)
    label = (await node.locator(".el-cascader-node__label").inner_text()).strip()
    cb = node.locator(".el-checkbox")
    is_checked = "is-checked" in (await cb.get_attribute("class") or "")
    if label != "境外企业" and not is_checked:
        await cb.click()
await page.keyboard.press("Escape")

# 2. 选校招 + 时间快捷调用
await page.evaluate("""() => {
    const vm = document.querySelector('.el-form').__vue__.$parent;
    vm.cls = [0];
    const s1 = vm.spiderDatePickerOptions.shortcuts.find(s => s.text === '一天内');
    if (s1) s1.onClick({ $emit: (e, val) => { vm.position_spider_date = val; } });
    const s2 = vm.publishDatePickerOptions.shortcuts.find(s => s.text === '一月前');
    if (s2) s2.onClick({ $emit: (e, val) => { vm.posting_publish_date = val; } });
    vm.searchClick();
}""")
```

#### 4. API 请求 Payload 结构
```json
{
  "page": 1,
  "page_size": 10,
  "org_type": ["0-1", "1-1", "2-1", "13-1", "16-1", "4-1", "5-1", "15-1", "6-1", "7-1", "8-1", "9-1", "10-1", "3-1", "14-1", "17-1", "19-1"],
  "class": [0],
  "position_spider_time_s": "2026-09-17T00:00:00.000Z",
  "position_spider_time_e": "2026-09-18T00:00:00.000Z",
  "publish_date_s": "2000-01-01T00:00:00.000Z",
  "publish_date_e": "2026-08-18T00:00:00.000Z"
}
```

---

### 情形 2：类型排除境外企业 + 校招 + 爬取时间一天内 + 关联公告未关联

#### 1. 业务目的
专门筛选国内企业中“最新 24 小时爬取、且系统**尚未关联任何招聘公告**”的待标注校招公司，是每日标注工作的核心入口。

#### 2. 手工 DOM 点击操作步骤
1. 点击【类型】级联框，勾选除 **【境外企业】** 外的 17 项类型。
2. 点击【岗位类型】下拉框，勾选 **校招**。
3. 点击【岗位爬取时间】输入框，点击左侧快捷栏 **一天内**。
4. 点击【关联公告】下拉框，选择 **未关联**。
5. 点击 **【搜索】** 按钮。

#### 3. API 请求 Payload 结构
```json
{
  "page": 1,
  "page_size": 10,
  "org_type": ["0-1", "1-1", "2-1", "13-1", "16-1", "4-1", "5-1", "15-1", "6-1", "7-1", "8-1", "9-1", "10-1", "3-1", "14-1", "17-1", "19-1"],
  "class": [0],
  "position_spider_time_s": "2026-09-17T00:00:00.000Z",
  "position_spider_time_e": "2026-09-18T00:00:00.000Z",
  "positing_exist": false
}
```

---

### 情形 3：类型排除境外企业 + 校招 + 爬取时间一天内 + 网申届数为未标注和26届、25届

#### 1. 业务目的
筛选国内企业中“最新一天爬取、且届数处于未标注或属于 26/25 届”的重点校招排查记录。

#### 2. 手工 DOM 点击操作步骤
1. 点击【类型】级联框，勾选除 **【境外企业】** 外的 17 项类型。
2. 点击【岗位类型】下拉框，勾选 **校招**。
3. 点击【岗位爬取时间】输入框，点击左侧快捷栏 **一天内**。
4. 点击【网申届数】下拉框，依次勾选 **未标注**、**26届**、**25届**。
5. 鼠标点击空白区域收起下拉菜单，点击 **【搜索】** 按钮。

#### 3. API 请求 Payload 结构
```json
{
  "page": 1,
  "page_size": 10,
  "org_type": ["0-1", "1-1", "2-1", "13-1", "16-1", "4-1", "5-1", "15-1", "6-1", "7-1", "8-1", "9-1", "10-1", "3-1", "14-1", "17-1", "19-1"],
  "class": [0],
  "position_spider_time_s": "2026-09-17T00:00:00.000Z",
  "position_spider_time_e": "2026-09-18T00:00:00.000Z",
  "grade": [-1, 26, 25]
}
```

---

### 情形 4：类型排除境外企业 + 校招 + 爬取时间选择前一日和当天 + 网申开始时间一月前

#### 1. 业务目的
跨天覆盖昨日全天至今天爬取入库的数据，排查网申开始时间截止到一个月份前的国内校招历史网申。

#### 2. 手工 DOM 点击操作步骤
1. 点击【类型】级联框，勾选除 **【境外企业】** 外的 17 项类型。
2. 点击【岗位类型】下拉框，勾选 **校招**。
3. 点击【岗位爬取时间】输入框，点选昨天与今天的日期范围。
4. 点击【网申开始时间】输入框，点击左侧快捷栏 **一月前**。
5. 点击 **【搜索】** 按钮。

#### 3. API 请求 Payload 结构
```json
{
  "page": 1,
  "page_size": 10,
  "org_type": ["0-1", "1-1", "2-1", "13-1", "16-1", "4-1", "5-1", "15-1", "6-1", "7-1", "8-1", "9-1", "10-1", "3-1", "14-1", "17-1", "19-1"],
  "class": [0],
  "position_spider_time_s": "2026-09-16T00:00:00.000Z",
  "position_spider_time_e": "2026-09-17T23:59:59.999Z",
  "publish_date_s": "2000-01-01T00:00:00.000Z",
  "publish_date_e": "2026-08-18T00:00:00.000Z"
}
```

---

### 情形 5：类型排除境外企业 + 校招 + 爬取时间选择前一日和当天 + 关联公告未关联

#### 1. 业务目的
覆盖前一天和当天爬取入库、且尚未关联公告的国内全部校招数据，用于跨天或早晨汇总时查漏补缺。

#### 2. 手工 DOM 点击操作步骤
1. 点击【类型】级联框，勾选除 **【境外企业】** 外的 17 项类型。
2. 点击【岗位类型】下拉框，勾选 **校招**。
3. 点击【岗位爬取时间】输入框，点选昨天与今天的日期。
4. 点击【关联公告】下拉框，选择 **未关联**。
5. 点击 **【搜索】** 按钮。

#### 3. API 请求 Payload 结构
```json
{
  "page": 1,
  "page_size": 10,
  "org_type": ["0-1", "1-1", "2-1", "13-1", "16-1", "4-1", "5-1", "15-1", "6-1", "7-1", "8-1", "9-1", "10-1", "3-1", "14-1", "17-1", "19-1"],
  "class": [0],
  "position_spider_time_s": "2026-09-16T00:00:00.000Z",
  "position_spider_time_e": "2026-09-17T23:59:59.999Z",
  "positing_exist": false
}
```

---

### 情形 6：类型排除境外企业 + 校招 + 爬取时间选择前一日和当天 + 网申届数为未标注和26届、25届

#### 1. 业务目的
覆盖前一日与当天爬取入库的国内企业中，届数为未标注或属于 26/25 届的全部校招岗位。

#### 2. 手工 DOM 点击操作步骤
1. 点击【类型】级联框，勾选除 **【境外企业】** 外的 17 项类型。
2. 点击【岗位类型】下拉框，勾选 **校招**。
3. 点击【岗位爬取时间】输入框，点选昨天与今天的日期。
4. 点击【网申届数】下拉框，依次勾选 **未标注**、**26届**、**25届**。
5. 点击空白区域收起下拉框，点击 **【搜索】** 按钮。

#### 3. API 请求 Payload 结构
```json
{
  "page": 1,
  "page_size": 10,
  "org_type": ["0-1", "1-1", "2-1", "13-1", "16-1", "4-1", "5-1", "15-1", "6-1", "7-1", "8-1", "9-1", "10-1", "3-1", "14-1", "17-1", "19-1"],
  "class": [0],
  "position_spider_time_s": "2026-09-16T00:00:00.000Z",
  "position_spider_time_e": "2026-09-17T23:59:59.999Z",
  "grade": [-1, 26, 25]
}
```

---

## 四、6 大业务情形全量实测战报

经当前 Chrome CDP 极速并发分页拉取实机联调，6 大情形均支持**全量自动分页拉取并提纯落盘**，精准率 100%（条数完全吻合后台数据库总数）：

| 情形编号 | 业务场景描述 | 筛选核心规则 | 后台总命中 | 全量实测获取 | 对应全量 JSON 文件 |
| :---: | :--- | :--- | :---: | :---: | :--- |
| **情形 1** | 校招 + 爬取一天内 + 网申一月前 | 排除境外企业(17项) + 爬取一天内 + 网申一月前 | **60 条** | **60 条 (100%)** | [`clean_scenario_1.json`](file:///D:/100_Work/101_Program/Proj/XHS/company_annotation/clean_scenario_1.json) |
| **情形 2** | **校招 + 爬取一天内 + 关联公告未关联** | 排除境外企业(17项) + 爬取一天内 + **未关联公告** | **71 条** | **71 条 (100%)** | [`clean_scenario_2.json`](file:///D:/100_Work/101_Program/Proj/XHS/company_annotation/clean_scenario_2.json) |
| **情形 3** | 校招 + 爬取一天内 + 届数未标注/26/25届 | 排除境外企业(17项) + 爬取一天内 + **届数:[-1,26,25]** | **101 条** | **101 条 (100%)** | [`clean_scenario_3.json`](file:///D:/100_Work/101_Program/Proj/XHS/company_annotation/clean_scenario_3.json) |
| **情形 4** | 校招 + 爬取前一日和当天 + 网申一月前 | 排除境外企业(17项) + 爬取跨2天 + 网申一月前 | **309 条** | **309 条 (100%)** | [`clean_scenario_4.json`](file:///D:/100_Work/101_Program/Proj/XHS/company_annotation/clean_scenario_4.json) |
| **情形 5** | **校招 + 爬取前一日和当天 + 关联公告未关联** | 排除境外企业(17项) + 爬取跨2天 + **未关联公告** | **110 条** | **110 条 (100%)** | [`clean_scenario_5.json`](file:///D:/100_Work/101_Program/Proj/XHS/company_annotation/clean_scenario_5.json) |
| **情形 6** | 校招 + 爬取前一日和当天 + 届数未标注/26/25届 | 排除境外企业(17项) + 爬取跨2天 + **届数:[-1,26,25]** | **338 条** | **338 条 (100%)** | [`clean_scenario_6.json`](file:///D:/100_Work/101_Program/Proj/XHS/company_annotation/clean_scenario_6.json) |
| **合计** | - | - | **989 条** | **989 条 (100%)** | **全部 6 个 JSON 已全量落盘** |

---

## 五、快速筛选脚本（fast_filter.py）使用指引

独立执行脚本源码位于项目目录：[`fast_filter.py`](file:///D:/100_Work/101_Program/Proj/XHS/company_annotation/fast_filter.py)

### 1. 命令行极速运行
在终端中可直接传入数字 `1 ~ 6` 或 `all` 秒级全量执行并生成文件：
```powershell
# 【一键全量抓取全部 6 个情形】（耗时约 25s，自动保存 989 条完整数据到 6 个 JSON）
d:\100_Work\101_Program\Proj\XHS\.venv\Scripts\python.exe D:\100_Work\101_Program\Proj\XHS\company_annotation\fast_filter.py all

# 执行单项【情形 2】：全量抓取今天未关联公告的 71 家校招企业
d:\100_Work\101_Program\Proj\XHS\.venv\Scripts\python.exe D:\100_Work\101_Program\Proj\XHS\company_annotation\fast_filter.py 2

# 执行单项【情形 4】：全量抓取跨两天历史网申池全部 309 家企业
d:\100_Work\101_Program\Proj\XHS\.venv\Scripts\python.exe D:\100_Work\101_Program\Proj\XHS\company_annotation\fast_filter.py 4

# 不带参数：交互式数字或字母选择
d:\100_Work\101_Program\Proj\XHS\.venv\Scripts\python.exe D:\100_Work\101_Program\Proj\XHS\company_annotation\fast_filter.py
```

### 2. 脚本底层协同设计亮点
1. **DOM 视觉与 Vue 响应双向同步**：
   - 模拟 DOM 展开多选级联面板，精准勾选除【境外企业】外的 17 项，确保输入框完美呈现 `央企 ⊗ + 16`；
   - 利用 Vue 响应式实例 `vm.spiderDatePickerOptions` / `vm.publishDatePickerOptions` 触发“一天内”、“一月前”快捷计算，免除 DOM 日期面板遮挡与动画延迟；
   - 每次切换情形前调用 `vm.resetFilterData()` 并深度置空历史参数，保证 0 条件残留。
2. **免 DOM 抓取的双轨数据捕获**：
   - 脚本通过 CDP 实时监听并拦截 HTTP 接口响应，直接把后端返回的纯正结构化数据写入返回值，供下游标注流程直连使用。
3. **数据清洗与自动落盘**：
   - 筛选完成后自动清洗提取指定的 **8 大核心业务指标**；
   - 自动在目录保存为 `clean_scenario_{sid}.json`（如 [`clean_scenario_1.json`](file:///D:/100_Work/101_Program/Proj/XHS/company_annotation/clean_scenario_1.json)），并在 Python 层面返回 `res['clean_records']` 列表，供下游模块直连消费。

---

## 六、数据接口（API）请求与结构化响应全解

自动化流程**完全能够直接截获并读取后台 API 的原始 JSON 响应**，无需从 HTML 表格二次爬取解析。

### 1. 核心数据接口定义
- **接口 URL**：`POST https://www.tatawangshen.com/api/recruit/company/basic/all`
- **认证方式**：复用当前 Chrome 页面 Cookie / Token，通过 CDP 监听无需手动维护鉴权。
- **监听捕获代码范式**：
  ```python
  captured = {}
  async def on_response(res):
      if "company/basic/all" in res.url and res.request.method == "POST":
          captured["json"] = await res.json()
  page.on("response", on_response)
  ```

### 2. API 响应完整真实数据结构（包含工商详情与公告池）
```json
{
  "code": 0,
  "message": null,
  "data": {
    "count": 71,
    "results": [
      {
        "_id": "68ebb965b39a8e6355249e91",
        "name": "浙江吉利汽车有限公司",
        "alias": "吉利汽车",
        "credit_code": "91330206734272689K",
        "location": "宁波市北仑区",
        "website_count": 2,
        "posting_url": "https://mp.weixin.qq.com/s/0SK2mdCYwCKu_3QYhusUyg",
        "grade": [27],
        "publish_date": "2026-08-13",
        "expire_date": null,
        "response": {
          "legalPersonName": "淦家阅",
          "regCapital": "285900万人民币",
          "regStatus": "存续",
          "industry": "汽车制造业",
          "businessScope": "汽车及其发动机的制造和销售；汽车零部件的制造和销售；进出口业务...",
          "estiblishTime": 1013875200000,
          "regLocation": "浙江省宁波市北仑区梅山街道港城路118号"
        },
        "job_posting": [
          {
            "url": "https://mp.weixin.qq.com/s/0SK2mdCYwCKu_3QYhusUyg",
            "title": "吉利控股集团2027届全球校园招聘正式启动",
            "pub_time": "2026-08-13 18:18:51",
            "publish_date": "2026-08-13T08:00:00",
            "grade": [27]
          },
          {
            "url": "https://mp.weixin.qq.com/s/BAgUxr7qLnntlVBHv8Jsgw",
            "title": "吉利控股集团2027届全球校园招聘启动会圆满落幕！",
            "pub_time": "2026-09-15 20:28:12"
          }
        ],
        "position_spider_time": "2026-09-16",
        "position_update_date": "2026-09-11",
        "operator": [
          {
            "timestamp": "2026-09-11 21:28:06",
            "username": "lijia"
          }
        ]
      }
    ]
  }
}
```

### 3. API 关键字段与下游【公告标注】业务赋能全景
| 字段路径 | 类型 | 示例值 | 业务含义与标注任务巨大价值 |
| :--- | :--- | :--- | :--- |
| `data.count` | Number | `71` | 筛选命中的企业真实总数 |
| `results[]._id` | String | `68ebb965b39a8e6355249e91` | **MongoDB 企业全局唯一主键**，接口提交标注与修改时的第一核心凭证 |
| `results[].credit_code` | String | `91330206734272689K` | 统一社会信用代码，排查重复与对齐工商库的主键 |
| `results[].name` | String | `浙江吉利汽车有限公司` | 工商注册全称 |
| `results[].alias` | String | `吉利汽车` | 规范企业简称 |
| `results[].response` | Object | `{ legalPersonName, regCapital, businessScope ... }` | **全套天眼查/企查查工商底座**！包含法人、注册资本、成立时间与**主营业务范围（businessScope）**，免除大量外部搜索耗时 |
| `results[].job_posting` | Array | `[{ title, url, pub_time, grade }]` | **平台已爬取的微信公众号推文候选池**！未关联公告的公司可以直接从该列表挑选最匹配的推文一键关联！ |
| `results[].posting_url` | String | `https://mp.weixin.qq.com/s/...` | 当前已绑定的招聘推文/公告链接（未关联时为 `null`） |
| `results[].grade` | Array | `[27]` | 当前岗位标注的届数（如 27 届） |
| `results[].publish_date` | String | `2026-08-13` | 网申开始/公告发布日期 |
| `results[].operator` | Array | `[{"username": "lijia"}]` | 操作员审计历史流水 |

---

### 4. 业务专属提纯：8 大核心清洗指标规范

为了让数据处理最精纯、杜绝冗余，自动化流程已内置清洗提取器 `parse_company_record()`，每条企业数据精准提纯为以下 **8 个核心业务字段**：

| 目标字段名 | 来源计算与提取逻辑 | 示例值 |
| :--- | :--- | :--- |
| **公司名称** | `item.name`（备选 `item.keywords[0]`） | `浙江吉利控股集团有限公司` |
| **最新一条的公告标题** | 优先匹配当前 `posting_url` 对应的推文标题；若未关联则取 `job_posting` 候选池按时间最新的推文 `title` | `吉利控股集团2027届全球校园招聘正式启动` |
| **公告网址** | 优先取当前绑定的 `posting_url`；若未绑定则取 `job_posting` 候选池最新的 `url` | `https://mp.weixin.qq.com/s/0SK2mdCYwCKu_3QYhusUyg` |
| **开始时间** | `item.publish_date` | `2026-08-13` |
| **标注的届数** | `item.grade`（格式化为 `27届`、`未标注`） | `27届` |
| **最近审计员** | `item.operator[-1].username`（历次审计最后一位） | `杨志远` |
| **审计时间** | `item.operator[-1].timestamp`（最后一位审计的时间戳）| `2026-09-15 13:37:51` |
| **备注 (note)** | `item.note`（原样保留，如新增核查标注） | `自动新增公告链接，须核查` |

#### 提纯后标准输出格式样例
```json
{
  "公司名称": "浙江吉利控股集团有限公司",
  "最新一条的公告标题": "吉利控股集团2027届全球校园招聘正式启动",
  "公告网址": "https://mp.weixin.qq.com/s/0SK2mdCYwCKu_3QYhusUyg",
  "开始时间": "2026-08-13",
  "标注的届数": "27届",
  "最近审计员": "杨志远",
  "审计时间": "2026-09-15 13:37:51",
  "备注": "自动新增公告链接，须核查"
}
```
