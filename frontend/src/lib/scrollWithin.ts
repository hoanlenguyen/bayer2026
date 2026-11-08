/** Bring `el` into view by scrolling only its nearest scrolling box (Ask's message list, the side panel).
 *  `scrollIntoView` also scrolls every ancestor, including the document: when a browser extension or a stray element
 *  makes the page a little taller than the window, the whole fixed-height Ask screen slid up and left blank space below.
 *  Where no ancestor scrolls (narrow screens, where the page itself scrolls), the browser's own behaviour is used. */
export function scrollWithin(el: Element, block: "start" | "nearest" = "nearest", behavior: ScrollBehavior = "auto") {
  let box = el.parentElement;
  while (box && box !== document.body) {
    const { overflowY } = getComputedStyle(box);
    if ((overflowY === "auto" || overflowY === "scroll") && box.scrollHeight > box.clientHeight) break;
    box = box.parentElement;
  }
  if (!box || box === document.body) { el.scrollIntoView({ block, behavior }); return; }
  const target = el.getBoundingClientRect(), frame = box.getBoundingClientRect();
  const top = target.top - frame.top + box.scrollTop;
  if (block === "start") { box.scrollTo({ top, behavior }); return; }
  if (target.top < frame.top) box.scrollTo({ top, behavior });
  else if (target.bottom > frame.bottom) box.scrollTo({ top: top + target.height - box.clientHeight, behavior });
}
