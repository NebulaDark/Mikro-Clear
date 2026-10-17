import test from 'node:test';
import assert from 'node:assert/strict';
import { ref } from 'vue';
import { createResourceLoader } from '../src/resourceLoader.js';

for (const label of ['refresh', 'navigation', 'search']) {
  test(`${label}: success → 503 → success clears data and recovers`, async () => {
    const data = ref([]);
    const error = ref('');
    let fail = false;
    const load = createResourceLoader(data, error, async () => {
      if (fail) throw new Error('HTTP 503');
      return ['current'];
    }, () => []);
    await load();
    assert.deepEqual(data.value, ['current']);
    fail = true;
    await load();
    assert.deepEqual(data.value, []);
    assert.equal(error.value, 'HTTP 503');
    fail = false;
    await load();
    assert.deepEqual(data.value, ['current']);
    assert.equal(error.value, '');
  });
}
