const http = require('http')

const HOST = process.env.PISTON_HOST || '127.0.0.1'
const PORT = Number(process.env.PISTON_PORT || 2000)
const LANGUAGES = ['python', 'node', 'go', 'java']

function req(method, path, body) {
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null
    const r = http.request(
      {
        host: HOST,
        port: PORT,
        path,
        method,
        headers: data
          ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) }
          : {},
      },
      (res) => {
        let buf = ''
        res.on('data', (c) => (buf += c))
        res.on('end', () => resolve({ status: res.statusCode, body: buf }))
      },
    )
    r.on('error', reject)
    if (data) r.write(data)
    r.end()
  })
}

async function waitReady() {
  for (let i = 0; i < 120; i++) {
    try {
      const res = await req('GET', '/api/v2/runtimes')
      if (res.status === 200) return
    } catch (e) {}
    await new Promise((r) => setTimeout(r, 1000))
  }
  throw new Error('piston API did not become ready')
}

async function installedLanguages() {
  const res = await req('GET', '/api/v2/runtimes')
  if (res.status !== 200) return []
  try {
    const runtimes = JSON.parse(res.body)
    return new Set(runtimes.map((rt) => rt.language))
  } catch (e) {
    return []
  }
}

async function main() {
  await waitReady()
  const installed = await installedLanguages()
  for (const lang of LANGUAGES) {
    if (installed.has(lang)) {
      console.log(`${lang} already installed, skipping`)
      continue
    }
    console.log(`installing ${lang}...`)
    const res = await req('POST', '/api/v2/packages', { language: lang, version: '*' })
    if (res.status === 200) {
      console.log(`installed ${lang}`)
      continue
    }
    let alreadyInstalled = false
    try {
      alreadyInstalled = JSON.parse(res.body).message === 'Already installed'
    } catch (e) {}
    if (alreadyInstalled) {
      console.log(`${lang} already installed, skipping`)
      continue
    }
    throw new Error(`install ${lang} failed: ${res.status} ${res.body}`)
  }
  console.log('runtime install complete')
}

main()
  .then(() => process.exit(0))
  .catch((e) => {
    console.error(e)
    process.exit(1)
  })
