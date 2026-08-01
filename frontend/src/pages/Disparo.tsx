import React, { useState } from 'react';

function Disparo() {
  const [messages, setMessages] = useState([{ type: 'text', content: '' }]);

  const handleAddMessage = () => {
    if (messages.length >= 3) {
      alert('Limite de 3 mensagens atingido para esse disparo.');
      return;
    }
    setMessages([...messages, { type: 'text', content: '' }]);
  };

  const handleSubmit = () => {
    const config = {
      messages,
    };
    console.log('Salvar config de disparo:', config);
  };

  return (
    <div>
      <h1>Configurar Disparo</h1>
      <p>Limite de 3 mensagens neste disparo</p>
      {messages.map((msg, idx) => (
        <div key={idx}>
          {/* Select de tipo e input de conteúdo, igual antes */}
        </div>
      ))}
      <button onClick={handleAddMessage}>Adicionar mensagem</button>
      <button onClick={handleSubmit}>Salvar Disparo</button>
    </div>
  );
}

export default Disparo;
