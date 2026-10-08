export default function({data, setStateValue}) {
  // Somente o identificador aleatório fica no navegador; os resultados ficam no servidor.
  try {
    const key = 'bob.workspace.v1';
    let token = localStorage.getItem(key);
    if (!/^[a-f0-9]{64}$/.test(token || '')) {
      token = data.token;
      localStorage.setItem(key, token);
    }
    if (token !== data.active) setStateValue('token', token);
  } catch {
    if (data.active !== data.token) setStateValue('token', data.token);
  }
}
