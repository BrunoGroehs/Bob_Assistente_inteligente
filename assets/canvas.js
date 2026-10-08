// Código local fixo: encaixe responsivo e movimentação sem sobreposição.
export default function({ data, setStateValue }) {
  const board = document.querySelector('.st-key-work_canvas');
  if (!board) return;
  const positions = structuredClone(data.positions || {});
  const manual = new Set(data.manual_ids || []);
  const cleanups = [], gap = 16;
  let moving = false, frame = 0;
  const layout = () => ({
    positions:Object.fromEntries(data.ids.filter(id => positions[id]).map(id => [id, positions[id]])),
    manual_ids:data.ids.filter(id => manual.has(id)),
  });
  let lastSaved = JSON.stringify(layout());
  const entries = data.ids.map(id => {
    const card = board.querySelector(`.st-key-card_${CSS.escape(id)}`);
    return { id, card, wrapper: card?.parentElement };
  }).filter(e => e.card);
  const mobile = () => board.clientWidth < 520;
  const dimensions = () => {
    const columns = Math.max(1, Math.floor((board.clientWidth + gap) / (380 + gap)));
    return {columns, width: (board.clientWidth - gap * (columns - 1)) / columns};
  };
  const collides = (a, b) => a.x < b.x + b.width + gap - .5 && a.x + a.width + gap > b.x + .5 && a.y < b.y + b.height + gap - .5 && a.y + a.height + gap > b.y + .5;
  const fit = (point, width, height, occupied) => {
    const p = {x: Math.max(0, Math.min(board.clientWidth - width, point.x)), y: Math.max(0, point.y), width, height};
    // Cada colisão desloca o cartão abaixo do obstáculo; nunca cobre outro cartão.
    for (let i = 0; i <= occupied.length; i++) {
      const hits = occupied.filter(other => collides(p, other));
      if (!hits.length) break;
      p.y = Math.max(...hits.map(other => other.y + other.height + gap));
    }
    return {x:p.x, y:p.y};
  };
  const save = () => {
    const current = layout();
    const serialized = JSON.stringify(current);
    if (serialized !== lastSaved) {
      lastSaved = serialized; setStateValue('layout', {revision:data.revision, ...current});
    }
  };
  const size = () => {
    if (moving || !board.clientWidth) return;
    if (mobile()) {
      entries.forEach(({wrapper}) => Object.assign(wrapper.style, {position:'relative', left:'', top:'', width:'100%'}));
      board.style.height = 'auto'; board.style.minHeight = '1px'; return;
    }
    const {columns, width} = dimensions();
    entries.forEach(({wrapper}) => {wrapper.style.width = `${width}px`;});
    const occupied = [];
    // Só o arraste fixa posições; cartões automáticos acompanham a largura atual.
    const ordered = [...entries].sort((a, b) => Number(manual.has(b.id)) - Number(manual.has(a.id)));
    ordered.forEach(({id, card, wrapper}) => {
      const candidates = Array.from({length:columns}, (_, column) =>
        fit({x:column * (width + gap), y:0}, width, card.offsetHeight, occupied));
      const p = manual.has(id) && positions[id]
        ? fit(positions[id], width, card.offsetHeight, occupied)
        : candidates.sort((a, b) => a.y - b.y || a.x - b.x)[0];
      positions[id] = p;
      Object.assign(wrapper.style, {position:'absolute', left:`${p.x}px`, top:`${p.y}px`});
      const rect = {...p, width, height:card.offsetHeight}; occupied.push(rect);
    });
    const bottom = Math.max(0, ...occupied.map(r => r.y + r.height + gap));
    board.style.height = `${bottom}px`; board.style.minHeight = `${bottom}px`;
    board.parentElement.style.flexShrink = '0'; save();
  };
  const place = (entry, point) => {
    const occupied = entries.filter(e => e.id !== entry.id).map(e => ({...positions[e.id], width:e.wrapper.offsetWidth, height:e.card.offsetHeight}));
    const p = fit(point, entry.wrapper.offsetWidth, entry.card.offsetHeight, occupied);
    manual.add(entry.id);
    positions[entry.id] = p;
    entry.wrapper.style.left = `${p.x}px`; entry.wrapper.style.top = `${p.y}px`;
  };
  entries.forEach(entry => {
    const {id, card} = entry;
    const handle = card.querySelector('.card-title');
    if (!handle) return;
    let stopDrag;
    const down = event => {
      if (mobile() || event.button !== 0) return;
      event.preventDefault(); size();
      const start = {...positions[id]}, px = event.clientX, py = event.clientY;
      moving = true; handle.setPointerCapture(event.pointerId);
      const move = e => place(entry, {x:start.x + e.clientX - px, y:Math.min(20000, start.y + e.clientY - py)});
      const up = () => {
        moving = false;
        handle.removeEventListener('pointermove', move); handle.removeEventListener('pointerup', up); handle.removeEventListener('pointercancel', up);
        stopDrag = null; size();
      };
      stopDrag = up;
      handle.addEventListener('pointermove', move); handle.addEventListener('pointerup', up); handle.addEventListener('pointercancel', up);
    };
    const key = event => {
      if (mobile() || !['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) return;
      event.preventDefault(); size();
      const p = positions[id];
      place(entry, {x:p.x + (event.key === 'ArrowLeft' ? -24 : event.key === 'ArrowRight' ? 24 : 0), y:Math.min(20000, p.y + (event.key === 'ArrowUp' ? -24 : event.key === 'ArrowDown' ? 24 : 0))});
      size();
    };
    handle.addEventListener('pointerdown', down); handle.addEventListener('keydown', key);
    cleanups.push(() => {if (stopDrag) stopDrag(); handle.removeEventListener('pointerdown', down); handle.removeEventListener('keydown', key);});
  });
  const observer = new ResizeObserver(() => {cancelAnimationFrame(frame); frame = requestAnimationFrame(size);});
  observer.observe(board); entries.forEach(e => observer.observe(e.card)); size();
  return () => {observer.disconnect(); cancelAnimationFrame(frame); cleanups.forEach(fn => fn());};
}
