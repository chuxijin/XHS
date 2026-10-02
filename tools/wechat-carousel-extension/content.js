chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message) {
    return;
  }

  if (message.type === "WECHAT_CAROUSEL_TOAST") {
    showToast(message.text || "已复制，请粘贴");
    sendResponse({ ok: true });
    return;
  }

  if (message.type === "WECHAT_CAROUSEL_INSERT_UNSAFE") {
    sendResponse({ ok: insertHtml(message.html) });
  }
});

function showToast(text) {
  const old = document.getElementById("wechat-carousel-helper-toast");
  if (old) {
    old.remove();
  }

  const toast = document.createElement("div");
  toast.id = "wechat-carousel-helper-toast";
  toast.textContent = text;
  toast.style.cssText = [
    "position:fixed",
    "z-index:2147483647",
    "right:24px",
    "top:24px",
    "max-width:320px",
    "padding:12px 14px",
    "border-radius:8px",
    "background:rgba(32,32,32,.92)",
    "color:#fff",
    "font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif",
    "box-shadow:0 10px 28px rgba(0,0,0,.18)"
  ].join(";");
  document.documentElement.appendChild(toast);
  window.setTimeout(() => toast.remove(), 2800);
}

function insertHtml(html) {
  const selection = window.getSelection();
  if (selection && selection.rangeCount > 0) {
    const range = selection.getRangeAt(0);
    const editable = closestEditable(range.commonAncestorContainer);
    if (editable) {
      range.deleteContents();
      range.insertNode(range.createContextualFragment(html));
      selection.removeAllRanges();
      selection.addRange(range);
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
