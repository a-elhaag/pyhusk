// Modern Interactive Scripts for pyhusk Documentation

document.addEventListener("DOMContentLoaded", () => {
  initCopyMarkdown();
});

// Support instant navigation in MkDocs Material
if (typeof document$ !== "undefined") {
  document$.subscribe(() => {
    initCopyMarkdown();
  });
}

function initCopyMarkdown() {
  const btn = document.getElementById("copy-markdown-btn");
  if (!btn || btn.dataset.initialized) return;
  btn.dataset.initialized = "true";

  btn.addEventListener("click", async () => {
    const article = document.querySelector(".md-content__inner");
    if (!article) return;

    let markdownText = "";

    // Try fetching raw source if path is known
    try {
      const currentPath = window.location.pathname;
      let filename = "index.md";
      const parts = currentPath.split("/").filter(Boolean);
      const lastPart = parts[parts.length - 1];

      if (lastPart && lastPart !== "docs") {
        filename = `${lastPart}.md`;
      }

      const rawUrl = `https://raw.githubusercontent.com/a-elhaag/pyhusk/master/docs_src/${filename}`;
      const res = await fetch(rawUrl);
      if (res.ok) {
        markdownText = await res.text();
      }
    } catch (e) {
      // Fallback to DOM conversion below
    }

    // Fallback: extract structured text if raw fetch unavailable
    if (!markdownText) {
      markdownText = extractMarkdownFromDom(article);
    }

    try {
      await navigator.clipboard.writeText(markdownText);
      const label = btn.querySelector(".btn-text");
      const originalText = label ? label.textContent : "Copy Markdown";
      
      btn.classList.add("copied");
      if (label) label.textContent = "Copied!";

      setTimeout(() => {
        btn.classList.remove("copied");
        if (label) label.textContent = originalText;
      }, 2000);
    } catch (err) {
      console.error("Failed to copy markdown: ", err);
    }
  });
}

function extractMarkdownFromDom(container) {
  const clone = container.cloneNode(true);
  const actions = clone.querySelector(".pyhusk-page-header");
  if (actions) actions.remove();

  let text = "";
  clone.querySelectorAll("h1, h2, h3, h4, p, pre, table, ul, ol").forEach((el) => {
    const tag = el.tagName.toLowerCase();
    const content = el.innerText.trim();
    if (!content) return;

    if (tag === "h1") text += `# ${content}\n\n`;
    else if (tag === "h2") text += `## ${content}\n\n`;
    else if (tag === "h3") text += `### ${content}\n\n`;
    else if (tag === "h4") text += `#### ${content}\n\n`;
    else if (tag === "pre") text += `\`\`\`\n${content}\n\`\`\`\n\n`;
    else if (tag === "p") text += `${content}\n\n`;
    else if (tag === "ul" || tag === "ol") text += `${content}\n\n`;
    else if (tag === "table") text += `${content}\n\n`;
  });

  return text.trim() || clone.innerText.trim();
}
