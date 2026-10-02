const state = {
  ratio: "3:4",
  slideType: "adsorb",
  width: 70,
  radius: 32,
  padding: 60,
  caption: "←左右滑动查看更多→\nSlide for more photos",
  images: [
    "https://mmbiz.qpic.cn/sz_mmbiz_png/dFHROBwvGZCY1h7VCNZRIWmiavFTYPtmRMBAIQ6ns0skdVH0349TYtL05DH9jfdOWZ7uDiady0DODEB3e0m51jlg/640?from=appmsg",
    "https://mmbiz.qpic.cn/sz_mmbiz_png/byobzsYuvS9iaeWqPf72L44xgY5eQWz0Tuoq3QonDgYrK78yYUzyO9XSdOxib6UY13ygzOYuw34RluG47HbsrKfQ/640?from=appmsg",
    "https://mmbiz.qpic.cn/sz_mmbiz_png/4esOJ82ANJsnKEAtiajFQ4gTfZXydsTiatfDQoib5cp3YN26jWTxLMicrGFmMawO2syiaaaJ8r8UlsP5q4XRXDKHbVA/640?from=appmsg"
  ]
};

const statusEl = document.getElementById("status");
const preview = document.getElementById("preview");
const imageInput = document.getElementById("imageInput");
const widthInput = document.getElementById("widthInput");
const radiusInput = document.getElementById("radiusInput");
const paddingInput = document.getElementById("paddingInput");
const captionInput = document.getElementById("captionInput");

init();

async function init() {
  const saved = await chrome.storage.local.get("wechatCarouselState");
  Object.assign(state, saved.wechatCarouselState || {});
  syncControls();
  bindEvents();
  render();
}

function bindEvents() {
  document.addEventListener("input", event => {
    const target = event.target;
    if (target.name === "ratio") {
      state.ratio = target.value;
    }
    if (target.name === "slideType") {
      state.slideType = target.value;
    }
    state.width = Number(widthInput.value) || 70;
    state.radius = Number(radiusInput.value) || 0;
    state.padding = Number(paddingInput.value) || 0;
    state.caption = captionInput.value;
    state.images = imageInput.value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    persist();
    render();
  });

  document.getElementById("copyBtn").addEventListener("click", async () => {
    await copyRichHtml(buildCarousel());
    setStatus("已复制");
  });

  document.getElementById("insertBtn").addEventListener("click", copyAndReturnToEditor);
}

function syncControls() {
  document.querySelectorAll("input[name='ratio']").forEach(input => {
    input.checked = input.value === state.ratio;
  });
  document.querySelectorAll("input[name='slideType']").forEach(input => {
    input.checked = input.value === state.slideType;
  });
  widthInput.value = state.width;
  radiusInput.value = state.radius;
  paddingInput.value = state.padding;
  captionInput.value = state.caption;
  imageInput.value = state.images.join("\n");
}

function persist() {
  chrome.storage.local.set({ wechatCarouselState: state });
}

function setStatus(text) {
  statusEl.textContent = text;
  window.setTimeout(() => {
    statusEl.textContent = "就绪";
  }, 1600);
}

function ratioSize() {
  const map = {
    "1:1": [1080, 1080],
    "3:2": [1080, 720],
    "3:4": [1080, 1440],
    "16:9": [1080, 607.5]
  };
  return map[state.ratio] || map["3:4"];
}

function escapeAttr(value) {
  return String(value).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

function escapeText(value) {
  return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function captionHtml() {
  return state.caption
    .split(/\r?\n/)
    .filter(Boolean)
    .map(line => `<p style="margin:0;"><span>${escapeText(line)}</span></p>`)
    .join("");
}

function buildCarousel() {
  const images = state.images.length ? state.images : [""];
  const count = images.length;
  const [viewW, viewH] = ratioSize();
  const pad = Math.max(0, Number(state.padding) || 0);
  const innerW = Math.max(1, viewW - pad * 2);
  const innerH = Math.max(1, viewH - pad * 2);
  const snapType = state.slideType === "adsorb" ? "x mandatory" : "none";
  const snapAlign = state.slideType === "adsorb" ? "start" : "none";
  const radius = Math.max(0, Number(state.radius) || 0);
  const width = Math.min(100, Math.max(40, Number(state.width) || 70));
  const items = images.map(url => {
    const safeUrl = escapeAttr(url.trim());
    return `        <section style="flex:1;vertical-align:top;display:flex;justify-content:center;align-items:center;scroll-snap-align:${snapAlign};">
          <svg style="width:100%;height:100%;" viewBox="0 0 ${viewW} ${viewH}">
            <foreignObject width="${innerW}" height="${innerH}" x="${pad}" y="${pad}">
              <section xmlns="http://www.w3.org/1999/xhtml" style="width:100%;height:100%;background-position:50% 50%;background-size:cover;background-repeat:no-repeat;border-radius:${radius}px;background-image:url(&quot;${safeUrl}&quot;);"></section>
            </foreignObject>
          </svg>
        </section>`;
  }).join("\n");

  return `<section><span><br></span></section>
<section style="width:${width}%;margin-left:auto!important;margin-right:auto!important;height:auto!important;">
  <section style="width:100%;">
    <section style="width:100%;overflow:scroll hidden;isolation:isolate;scroll-snap-type:${snapType};scroll-behavior:smooth;scrollbar-width:thin;-webkit-scrollbar-width:thin;line-height:0;pointer-events:visible;">
      <section style="white-space:nowrap;width:${count * 100}%!important;max-width:${count * 100}%!important;display:flex;line-height:0;">
${items}
      </section>
    </section>
    <section style="padding:12px;text-align:center;max-height:78px;overflow-x:hidden;overflow-y:auto;isolation:isolate;scroll-behavior:smooth;scrollbar-width:thin;-webkit-scrollbar-width:thin;box-sizing:border-box;font-size:12px;font-family:PingFangSC-Regular, PingFang SC;color:#999;line-height:18px;">
      ${captionHtml()}
    </section>
  </section>
</section>
<section><span><br></span></section>`;
}

function render() {
  preview.innerHTML = buildCarousel();
}

async function copyRichHtml(html) {
  if (navigator.clipboard && window.ClipboardItem) {
    const item = new ClipboardItem({
      "text/html": new Blob([html], { type: "text/html" }),
      "text/plain": new Blob([html], { type: "text/plain" })
    });
    await navigator.clipboard.write([item]);
    return;
  }

  const copySource = document.createElement("div");
  copySource.contentEditable = "true";
  copySource.style.position = "fixed";
  copySource.style.left = "-9999px";
  copySource.innerHTML = html;
  document.body.appendChild(copySource);
  const range = document.createRange();
  range.selectNodeContents(copySource);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  document.execCommand("copy");
  selection.removeAllRanges();
  copySource.remove();
}

async function copyAndReturnToEditor() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const html = buildCarousel();
  await copyRichHtml(html);
  setStatus("已复制，请粘贴");

  if (tab && tab.id) {
    chrome.tabs.sendMessage(tab.id, {
      type: "WECHAT_CAROUSEL_TOAST",
      text: "横滑组件已复制，请在正文光标处按 Ctrl+V 粘贴"
    }).catch(() => {});
  }

  window.setTimeout(() => {
    window.close();
  }, 650);
}

async function insertIntoPageUnsafe() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) {
    setStatus("未找到页面");
    return;
  }

  const html = buildCarousel();
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      func: insertHtmlInFrame,
      args: [html]
    });
    const inserted = results.some(result => result.result === true);
    if (inserted) {
      setStatus("已插入");
      return;
    }
  } catch (error) {
    console.warn(error);
  }

  await copyRichHtml(html);
  setStatus("已复制，请粘贴");
}

function insertHtmlInFrame(html) {
  function closestEditable(node) {
    let current = node && node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
    while (current) {
      if (current.isContentEditable) {
        return current;
      }
      current = current.parentElement;
    }
    return null;
  }

  const selection = window.getSelection();
  if (selection && selection.rangeCount > 0) {
    const range = selection.getRangeAt(0);
    const editable = closestEditable(range.commonAncestorContainer);
    if (editable) {
      range.deleteContents();
      range.insertNode(range.createContextualFragment(html));
      editable.dispatchEvent(new InputEvent("input", {
        bubbles: true,
        inputType: "insertHTML",
        data: html
      }));
      return true;
    }
  }

  const active = document.activeElement;
  if (active && active.isContentEditable) {
    active.focus();
    document.execCommand("insertHTML", false, html);
    active.dispatchEvent(new InputEvent("input", {
      bubbles: true,
      inputType: "insertHTML",
      data: html
    }));
    return true;
  }

  return false;
}
