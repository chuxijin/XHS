/**
 * 飞书表格数据快速抓取脚本 (通过 Chrome Debugging Port 9222)
 * 用法:
 *   node fetch_feishu_sheet.js [目标日期，如 2026-09-24，不传则默认当天或最新日期]
 */

const WebSocket = globalThis.WebSocket;

async function fetchFeishuSheetData(targetDate) {
    // 1. 获取 Chrome 9222 端口上的飞书页面
    let targets;
    try {
        const res = await fetch('http://127.0.0.1:9222/json');
        targets = await res.json();
    } catch (e) {
        console.error('无法连接到 Chrome 调试端口 9222，请确保 Chrome 已用 --remote-debugging-port=9222 启动！');
        process.exit(1);
    }

    const feishuTarget = targets.find(t => t.url && t.url.includes('feishu.cn') && t.type === 'page');
    if (!feishuTarget) {
        console.error('未在 Chrome 中找到打开的飞书页面！');
        process.exit(1);
    }

    // 2. 连接 WebSocket
    const ws = new WebSocket(feishuTarget.webSocketDebuggerUrl);
    let reqId = 1;
    const send = (method, params = {}) => new Promise((resolve, reject) => {
        const id = reqId++;
        const handler = (evt) => {
            const data = JSON.parse(evt.data);
            if (data.id === id) {
                ws.removeEventListener('message', handler);
                if (data.error) reject(data.error);
                else resolve(data.result);
            }
        };
        ws.addEventListener('message', handler);
        ws.send(JSON.stringify({ id, method, params }));
    });

    await new Promise(r => ws.onopen = r);

    // 3. 在页面上下文中通过 React Fiber 获取 spread 实例并提取数据
    const evalCode = `(() => {
        // 查找公式栏 React Fiber
        const el = document.querySelector('.formulabar__inputarea');
        if (!el) return { error: '未找到公式栏元素，请确保表格已加载完毕' };

        const rk = Object.keys(el).find(k => k.startsWith('__reactInternalInstance') || k.startsWith('__reactFiber'));
        let cur = el[rk];
        let spread = null;
        while (cur) {
            if (cur.memoizedProps && cur.memoizedProps.spread) {
                spread = cur.memoizedProps.spread;
                break;
            }
            cur = cur.return;
        }

        if (!spread) return { error: '未在 React Fiber 中找到 spread 实例' };

        const sheet = spread.getActiveSheet();
        if (!sheet) return { error: '无法获取 activeSheet' };

        // 读取表头
        const headers = [];
        for (let c = 0; c < 15; c++) {
            const h = sheet.getText ? sheet.getText(1, c) : '';
            headers.push(h ? h.replace(/\\n/g, '') : \`Col_\${c}\`);
        }

        // 读取数据行 (从第 2 行开始，飞书 0-indexed，行 1 为表头，行 2 为第一行数据)
        const rowCount = typeof sheet.getRowCount === 'function' ? sheet.getRowCount() : 100;
        const rows = [];

        for (let r = 2; r < Math.min(rowCount, 300); r++) {
            const dateText = sheet.getText(r, 0);
            if (!dateText) break; // 空行停止

            const rowData = {};
            for (let c = 0; c < headers.length; c++) {
                const header = headers[c];
                const text = sheet.getText ? sheet.getText(r, c) : '';
                const segments = sheet.getSegmentArray ? sheet.getSegmentArray(r, c) : null;
                
                // 检查是否有富文本超链接
                let link = null;
                if (segments && Array.isArray(segments)) {
                    for (const seg of segments) {
                        if (seg.link) {
                            link = seg.link;
                            break;
                        }
                    }
                }

                rowData[header] = text;
                if (link) {
                    rowData[header + '_url'] = link;
                }
            }
            rows.push(rowData);
        }

        return { headers, rows };
    })()`;

    const res = await send('Runtime.evaluate', {
        expression: evalCode,
        returnByValue: true
    });

    ws.close();

    const data = res.result.value;
    if (data.error) {
        console.error('抓取失败:', data.error);
        process.exit(1);
    }

    // 4. 根据目标日期过滤
    let filtered = data.rows;
    if (targetDate) {
        filtered = data.rows.filter(r => r['更新日期'] === targetDate || (r['更新日期'] && r['更新日期'].includes(targetDate)));
    }

    return filtered;
}

// 命令行执行入口
const dateArg = process.argv[2] || '2026-09-24';
fetchFeishuSheetData(dateArg).then(rows => {
    console.log(JSON.stringify(rows, null, 2));
}).catch(console.error);
