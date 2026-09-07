const { TwaManifest } = require('@bubblewrap/core');

async function main() {
  const twaManifest = await TwaManifest.fromWebManifest(
    'https://alume-tech.onrender.com/static/manifest-app.json',
  );
  twaManifest.packageId = 'com.alumetech.app';
  twaManifest.launcherName = 'Alume Tech';
  twaManifest.name = 'Alume Tech';
  twaManifest.signingKey = { path: './android.keystore', alias: 'android' };
  twaManifest.appVersionName = '1.0.0';
  twaManifest.appVersionCode = 1;
  await twaManifest.saveToFile('./twa-manifest.json');
  console.log('twa-manifest.json written');
  console.log(JSON.stringify(twaManifest.toJson(), null, 2));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
