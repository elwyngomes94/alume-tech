const path = require('path');
const { updateProject } = require('@bubblewrap/cli/dist/lib/cmds/shared.js');

// Prompt que nunca pergunta nada -- so aceita os valores padrao (usado para
// gerar o projeto Android sem nenhuma interacao, ja que este ambiente nao
// tem um terminal interativo de verdade para responder aos wizards do
// Bubblewrap.
const silentPrompt = {
  async printMessage(message) {
    console.log(message);
  },
  async promptInput(message, defaultValue) {
    return defaultValue;
  },
  async promptConfirm(message, defaultValue) {
    return defaultValue;
  },
  async promptPassword(message) {
    return process.env.BUBBLEWRAP_KEYSTORE_PASSWORD || '';
  },
};

async function main() {
  const manifestFile = path.join(process.cwd(), 'twa-manifest.json');
  const ok = await updateProject(true, null, silentPrompt, process.cwd(), manifestFile);
  console.log('updateProject result:', ok);
  if (!ok) process.exit(1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
