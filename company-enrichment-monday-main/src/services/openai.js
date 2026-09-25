import axios from 'axios';
import { env } from '../config/env.js';
import { log } from '../lib/logger.js';

const RESPONSES_URL = 'https://api.openai.com/v1/responses';

/** Matches the retry ladder the previous deployment logged: 1s, 2s, 4s. */
const RETRY_DELAYS_MS = [1000, 2000, 4000];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Runs the research prompt through the Responses API with the web_search tool.
 *
 * The prompt demands 15-20 live searches against handelsregister.de, Impressum
 * pages and so on, so the tool is the point - without it the model answers from
 * memory and every HIGH confidence it reports is fiction.
 */
export async function research(prompt) {
  let useWebSearch = true;

  for (let attempt = 0; ; attempt += 1) {
    try {
      const { data } = await axios.post(
        RESPONSES_URL,
        {
          model: env.openai.model,
          input: prompt,
          ...(useWebSearch ? { tools: [{ type: 'web_search' }], tool_choice: 'auto' } : {}),
        },
        {
          timeout: env.openai.timeoutMs,
          headers: {
            Authorization: `Bearer ${env.openai.apiKey}`,
            'Content-Type': 'application/json',
          },
        },
      );

      return { text: extractText(data), searched: useWebSearch, searchCount: countSearches(data) };
    } catch (error) {
      const status = error.response?.status;
      const message = JSON.stringify(error.response?.data || '');

      if (useWebSearch && status === 400 && /web_search|tool/i.test(message)) {
        log(`OpenAI: model ${env.openai.model} rejected the web_search tool - retrying without it`);
        useWebSearch = false;
        continue;
      }

      if (status === 429 && attempt < RETRY_DELAYS_MS.length) {
        const delay = RETRY_DELAYS_MS[attempt];
        log(`OpenAI 429 — retry ${attempt + 1}/${RETRY_DELAYS_MS.length} after ${delay}ms`);
        await sleep(delay);
        continue;
      }

      throw error;
    }
  }
}

function extractText(data) {
  if (typeof data?.output_text === 'string' && data.output_text.trim()) return data.output_text;

  const chunks = [];
  for (const item of data?.output || []) {
    for (const part of item?.content || []) {
      if (part?.type === 'output_text' && part.text) chunks.push(part.text);
    }
  }
  return chunks.join('\n');
}

function countSearches(data) {
  return (data?.output || []).filter((item) => item?.type === 'web_search_call').length;
}
