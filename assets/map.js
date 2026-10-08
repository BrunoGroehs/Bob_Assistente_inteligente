export default function({data, parentElement, setTriggerValue}) {
  const root = parentElement.querySelector('.bob-map');
  root.innerHTML = data.svg; // SVG produzido e escapado exclusivamente pelo renderizador local.
  const svg = root.querySelector('svg');
  const toolbar = document.createElement('div');
  toolbar.className = 'map-toolbar';
  const hint = document.createElement('span');
  hint.textContent = data.estado ? data.label : 'Passe o mouse para ver valores · clique para ampliar';
  toolbar.append(hint);
  if (data.estado) {
    const back = document.createElement('button');
    back.textContent = 'Voltar ao Brasil';
    back.onclick = () => setTriggerValue('estado', 'Brasil');
    toolbar.append(back);
  }
  root.prepend(toolbar);
  const tip = document.createElement('div');
  tip.className = 'map-tooltip';
  root.append(tip);
  svg.querySelectorAll('path').forEach(path => {
    const title = path.querySelector('title')?.textContent || '';
    const uf = path.dataset.uf;
    path.setAttribute('aria-label', title);
    const show = () => {tip.textContent = title; tip.hidden = false;};
    path.onpointerenter = show;
    path.onfocus = show;
    path.onpointerleave = () => {tip.hidden = true;};
    path.onblur = () => {tip.hidden = true;};
    if (!data.ufs.includes(uf)) return;
    path.setAttribute('tabindex','0');
    path.setAttribute('role','button');
    path.onclick = () => setTriggerValue('estado', data.estado ? 'Brasil' : uf);
    path.onkeydown = e => {if (e.key === 'Enter' || e.key === ' ') {e.preventDefault(); path.onclick();}};
  });
  tip.hidden = true;
}
