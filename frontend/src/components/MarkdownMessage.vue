<script setup>
import hljs from 'highlight.js'
import MarkdownIt from 'markdown-it'
import 'highlight.js/styles/github.css'

const props = defineProps({
  content: {
    type: String,
    required: true,
  },
  imageUrls: {
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

function contentWithToolImages(content) {
  const missingUrls = [...new Set(props.imageUrls)]
    .filter((url) => url && !content.includes(String(url)))

  if (!missingUrls.length) return content

  const images = missingUrls
    .map((url) => `![生成的图表](<${String(url).replaceAll('>', '%3E')}>)`)
    .join('\n\n')

  // 工具只返回图片地址时，将图表补到正文第一段之后，保持回答的阅读顺序。
  const firstParagraphEnd = content.indexOf('\n\n')
  if (firstParagraphEnd === -1) return `${content}\n\n${images}`

  return `${content.slice(0, firstParagraphEnd)}\n\n${images}${content.slice(firstParagraphEnd)}`
}

</script>

<template>
  <div class="markdown-body" v-html="md.render(contentWithToolImages(props.content))" />
</template>
