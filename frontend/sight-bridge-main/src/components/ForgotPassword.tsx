import React, { useState } from 'react';
import axios from 'axios';

const ForgotPassword = () => {
    const [email, setEmail] = useState('');
    const [message, setMessage] = useState('');

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            // Appel à votre API Django
            const response = await axios.post('/api/request-reset/', { email });
            setMessage(response.data.message || response.data.error);
        } catch (error) {
            setMessage("Une erreur est survenue.");
        }
    };

    return (
        <div>
            <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                    <input 
                        type="email" 
                        placeholder="Votre email" 
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        required 
                        className="w-full rounded-lg border border-slate-200 bg-white py-2.5 px-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
                    />
                </div>
                <button 
                    type="submit"
                    className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:opacity-50"
                >
                    Recevoir le lien
                </button>
            </form>
            {message && <p className="mt-4 text-sm text-center text-slate-600">{message}</p>}
        </div>
    );
};

export default ForgotPassword;
