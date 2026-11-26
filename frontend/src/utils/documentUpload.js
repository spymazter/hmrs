const MAX_BYTES = 1024 * 1024
const MAX_DIMENSION = 2000

function isImage(file) {
  return /^image\/(jpeg|png)$/i.test(file.type) || /\.(jpe?g|png)$/i.test(file.name)
}

function readAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(new Error('Could not read the image'))
    reader.readAsDataURL(file)
  })
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('Could not open the image'))
    image.src = src
  })
}

function canvasToBlob(canvas, quality) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error('Could not compress the image'))),
      'image/jpeg',
      quality,
    )
  })
}

function drawScaled(image, width, height) {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d')
  context.fillStyle = '#ffffff'
  context.fillRect(0, 0, width, height)
  context.drawImage(image, 0, 0, width, height)
  return canvas
}

async function compressImage(file) {
  const image = await loadImage(await readAsDataUrl(file))
  const initialScale = Math.min(1, MAX_DIMENSION / Math.max(image.width, image.height))
  let width = Math.max(1, Math.round(image.width * initialScale))
  let height = Math.max(1, Math.round(image.height * initialScale))
  let canvas = drawScaled(image, width, height)
  let quality = 0.85
  let blob = await canvasToBlob(canvas, quality)

  while (blob.size > MAX_BYTES && quality > 0.35) {
    quality = Math.max(0.35, quality - 0.1)
    blob = await canvasToBlob(canvas, quality)
  }

  let shrink = 0.85
  while (blob.size > MAX_BYTES && shrink > 0.4) {
    width = Math.max(1, Math.round(width * shrink))
    height = Math.max(1, Math.round(height * shrink))
    canvas = drawScaled(image, width, height)
    blob = await canvasToBlob(canvas, quality)
    shrink -= 0.15
  }

  if (blob.size > MAX_BYTES) {
    throw new Error('Unable to compress this image below 1 MB')
  }

  const name = file.name.replace(/\.(png|jpe?g)$/i, '.jpg')
  return new File([blob], name, { type: 'image/jpeg', lastModified: Date.now() })
}

/** Compress oversized images; reject other file types that exceed 1 MB. */
export async function prepareDocument(file) {
  if (!file) throw new Error('Choose a file to upload')
  if (file.size <= MAX_BYTES) return file
  if (!isImage(file)) {
    throw new Error('Files must be 1 MB or less — please compress the file before uploading')
  }
  return compressImage(file)
}

export const DOCUMENT_SIZE_MB = 1
