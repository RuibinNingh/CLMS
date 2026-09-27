/** 读本地图片文件：readImages(files) → Promise<[{ name, data(dataURL) }]>，非图片文件直接跳过。 */
export const readImages = files => Promise.all([...(files || [])].filter(f => f.type.startsWith('image/')).map(file => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve({ name: file.name || '截图.png', data: reader.result });
  reader.onerror = () => reject(reader.error);
  reader.readAsDataURL(file);
})));
