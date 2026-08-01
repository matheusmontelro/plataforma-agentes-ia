const dotenv = require('dotenv');
const path = require('path');

// Carrega explicitamente o .env.development
const result = dotenv.config({ path: path.resolve(__dirname, '.env.development') });

if (result.error) {
  console.error('--- TEST SCRIPT --- Erro ao carregar .env.development:', result.error);
} else {
  console.log('--- TEST SCRIPT --- .env.development carregado com sucesso:', result.parsed);
}

console.log('Valor de process.env.REACT_APP_API_URL:', process.env.REACT_APP_API_URL);
console.log('--- END TEST SCRIPT ---');
