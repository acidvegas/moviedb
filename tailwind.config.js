// moviedb - Developed by acidvegas in JavaScript (https://github.com/acidvegas/moviedb)
// tailwind.config.js

module.exports = {
	content: ['./templates/**/*.html', './app.py', './static/utils.js'],
	darkMode: 'class',
	theme: {extend: {fontFamily: {sans: ['Inter', 'system-ui', 'sans-serif']}, colors: {accent: {DEFAULT: '#f5c518', dim: '#b8940f'}}}}
}
