import React from "react";

// Tiny, dependency-free markdown renderer — handles the subset the AI chapter
// notes use: #/##/### headings, - / * bullet lists, 1. ordered lists, **bold**,
// *italic*, `code`, and paragraphs. Not a full CommonMark parser; intentionally
// small so we add no heavy dependency.

// Inline: **bold**, *italic*, `code`. Returns an array of React nodes.
function renderInline(text, keyPrefix) {
  const nodes = [];
  // Split on the inline tokens while keeping them.
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let last = 0;
  let m;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyPrefix}-i${i++}`;
    if (tok.startsWith("**")) {
      nodes.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith("`")) {
      nodes.push(<code key={key}>{tok.slice(1, -1)}</code>);
    } else {
      nodes.push(<em key={key}>{tok.slice(1, -1)}</em>);
    }
    last = m.index + tok.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

export default function Markdown({ md }) {
  if (!md) return null;
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let list = null; // { type: "ul"|"ol", items: [] }
  let para = []; // buffered paragraph lines

  function flushPara(key) {
    if (para.length) {
      blocks.push(<p key={`p${key}`} className="md-p">{renderInline(para.join(" "), `p${key}`)}</p>);
      para = [];
    }
  }
  function flushList(key) {
    if (list) {
      const items = list.items.map((it, idx) => (
        <li key={`li${key}-${idx}`}>{renderInline(it, `li${key}-${idx}`)}</li>
      ));
      blocks.push(
        list.type === "ol"
          ? <ol key={`l${key}`} className="md-list">{items}</ol>
          : <ul key={`l${key}`} className="md-list">{items}</ul>
      );
      list = null;
    }
  }

  lines.forEach((raw, idx) => {
    const line = raw.trimEnd();
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    const bullet = /^[-*]\s+(.*)$/.exec(line);
    const ordered = /^\d+\.\s+(.*)$/.exec(line);

    if (heading) {
      flushPara(idx); flushList(idx);
      const level = Math.min(heading[1].length, 4);
      const Tag = `h${Math.min(level + 1, 6)}`; // h1->h2 etc. to fit card scale
      blocks.push(<Tag key={`h${idx}`} className={`md-h md-h${level}`}>{renderInline(heading[2], `h${idx}`)}</Tag>);
    } else if (bullet) {
      flushPara(idx);
      if (!list || list.type !== "ul") { flushList(idx); list = { type: "ul", items: [] }; }
      list.items.push(bullet[1]);
    } else if (ordered) {
      flushPara(idx);
      if (!list || list.type !== "ol") { flushList(idx); list = { type: "ol", items: [] }; }
      list.items.push(ordered[1]);
    } else if (line.trim() === "") {
      flushPara(idx); flushList(idx);
    } else {
      flushList(idx);
      para.push(line.trim());
    }
  });
  flushPara("end"); flushList("end");

  return <div className="markdown">{blocks}</div>;
}
