import assert from 'node:assert/strict'
import test from 'node:test'
import { PrometheaClient, PrometheaError } from '../dist/index.js'

test('project metadata uses existing authenticated HTTP transport and public shapes', async () => {
  const calls = []
  const project = { project_id: 'p /1', name: 'Notes', session_ids: ['s/1'], created_at: '2026-10-20', updated_at: '2026-10-20' }
  const client = new PrometheaClient({ baseUrl: 'https://runtime.example', token: 'token', fetch: async (url, init) => {
    init = { ...init, method: init.method || 'GET' }
    calls.push({ url, init })
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer token')
    if (['DELETE', 'PUT'].includes(init.method)) return new Response(null, { status: 204 })
    return Response.json(init.method === 'GET' ? { projects: [project] } : project)
  } })
  assert.deepEqual((await client.projects.list()).projects, [project])
  assert.deepEqual(await client.projects.create({ name: 'Notes' }), project)
  await client.projects.rename('p /1', { name: 'Writing' })
  await client.projects.assignSession('s/1', 'p /1')
  await client.projects.assignSession('s/1', null)
  await client.projects.delete('p /1')
  assert.deepEqual(calls.map(call => [call.init.method, new URL(call.url).pathname]), [['GET', '/api/projects'], ['POST', '/api/projects'], ['PATCH', '/api/projects/p%20%2F1'], ['PUT', '/api/sessions/s%2F1/project'], ['PUT', '/api/sessions/s%2F1/project'], ['DELETE', '/api/projects/p%20%2F1']])
  assert.deepEqual(JSON.parse(calls[1].init.body), { name: 'Notes' })
  assert.deepEqual(JSON.parse(calls[4].init.body), { project_id: null })
})
test('project assignment never swallows ownership errors', async () => {
  const client = new PrometheaClient({ baseUrl: 'https://runtime.example', fetch: async () => Response.json({ error_detail: { code: 'NOT_FOUND', message: 'Project not found' } }, { status: 404 }) })
  await assert.rejects(client.projects.assignSession('s', 'foreign'), error => error instanceof PrometheaError && error.status === 404 && error.message === 'Project not found')
})
