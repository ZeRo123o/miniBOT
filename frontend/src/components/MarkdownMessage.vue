<script setup>
import hljs from 'highlight.js'
import MarkdownIt from 'markdown-it'
import 'highlight.js/styles/github.css'

const props = defineProps({
  content: {
    type: String,
    required: true,
  },
  hiddenImageUrls: {
    type: Array,
    default: () => [],
  },
})

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang }).value
    }
    return md.utils.escapeHtml(code)
  },
})

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function withoutRenderedChartImages(content) {
  return props.hiddenImageUrls.reduce(
    (result, url) => result.replace(
      new RegExp(`!\\[[^\\]]*\\]\\(${escapeRegExp(String(url))}(?:\\s+[^)]*)?\\)`, 'g'),
      '',
    ),
    content,
  )
}
</script>

<template>
  <div class="markdown-body" v-html="md.render(withoutRenderedChartImages(props.content))" />
</template>
