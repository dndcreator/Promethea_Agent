import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import process from 'node:process'


const root = resolve(import.meta.dirname, '../../..')
const generator = resolve(root, 'scripts/generate_public_contracts.py')
const localCandidates = process.platform === 'win32'
  ? [resolve(root, '../.venv/Scripts/python.exe')]
  : [resolve(root, '../.venv/bin/python')]
const candidates = [
  process.env.PYTHON,
  ...localCandidates.filter(existsSync),
  'python3',
  'python',
].filter(Boolean)

for (const executable of candidates) {
  const result = spawnSync(executable, [generator, ...process.argv.slice(2)], {
    cwd: root,
    stdio: 'inherit',
  })
  if (!result.error) process.exit(result.status ?? 1)
}

console.error('Python was not found. Activate the Promethea virtual environment or set PYTHON.')
process.exit(1)
