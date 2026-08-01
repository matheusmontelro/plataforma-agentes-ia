import React, { useRef, useEffect } from 'react';
import { Building, Phone, MapPin, Instagram, Facebook, Globe, MessageCircle, Map, FileText } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext.tsx';

interface CompanyInfoFormProps {
  companyName: string;
  setCompanyName: (val: string) => void;
  companyLocation: string;
  setCompanyLocation: (val: string) => void;
  companyAddress: string;
  setCompanyAddress: (val: string) => void;
  companyPhoneFixed: string;
  setCompanyPhoneFixed: (val: string) => void;
  companyWhatsApp: string;
  setCompanyWhatsApp: (val: string) => void;
  companyMaps: string;
  setCompanyMaps: (val: string) => void;
  companyInstagram: string;
  setCompanyInstagram: (val: string) => void;
  companyFacebook: string;
  setCompanyFacebook: (val: string) => void;
  companySite: string;
  setCompanySite: (val: string) => void;
  companyHistory: string;
  setCompanyHistory: (val: string) => void;
}

// Helper components (seguindo padrão do AssistantIdentityForm)
const Field: React.FC<{ label: string; children: React.ReactNode; hint?: string }> = ({ label, children, hint }) => {
  const { isDark } = useTheme();
  return (
    <label className="block text-sm">
      <span className={`mb-1 block ${
        isDark ? 'text-gray-300' : 'text-gray-700'
      }`}>{label}</span>
      {children}
      {hint && <span className={`mt-1 block text-[11px] ${
        isDark ? 'text-gray-400' : 'text-gray-500'
      }`}>{hint}</span>}
    </label>
  );
};

const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>((props, ref) => {
  const { isDark } = useTheme();
  return (
    <input
      ref={ref}
      {...props}
      className={`w-full rounded-xl border px-3 py-2 text-sm outline-none transition-all focus:ring-2 focus:ring-brand ${
        isDark
          ? 'border-gray-600 bg-gray-700 text-gray-200 placeholder:text-gray-400 focus:border-brand'
          : 'border-gray-300 bg-white text-gray-800 placeholder:text-gray-400 focus:border-brand'
      } ${props.className ?? ""}`}
    />
  );
});

const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>((props, ref) => {
  const { isDark } = useTheme();
  return (
    <textarea
      ref={ref}
      {...props}
      className={`w-full rounded-xl border px-3 py-2 text-sm outline-none transition-all focus:ring-2 focus:ring-brand ${
        isDark
          ? 'border-gray-600 bg-gray-700 text-gray-200 placeholder:text-gray-400 focus:border-brand'
          : 'border-gray-300 bg-white text-gray-800 placeholder:text-gray-400 focus:border-brand'
      } ${props.className ?? ""}`}
    />
  );
});

const CompanyInfoForm: React.FC<CompanyInfoFormProps> = ({
  companyName, setCompanyName,
  companyLocation, setCompanyLocation,
  companyAddress, setCompanyAddress,
  companyPhoneFixed, setCompanyPhoneFixed,
  companyWhatsApp, setCompanyWhatsApp,
  companyMaps, setCompanyMaps,
  companyInstagram, setCompanyInstagram,
  companyFacebook, setCompanyFacebook,
  companySite, setCompanySite,
  companyHistory, setCompanyHistory,
}) => {
  const { isDark } = useTheme();

  // Refs para os inputs (funcionalidade original)
  const nameRef = useRef<HTMLInputElement>(null);
  const locationRef = useRef<HTMLInputElement>(null);
  const addressRef = useRef<HTMLInputElement>(null);
  const phoneFixedRef = useRef<HTMLInputElement>(null);
  const whatsAppRef = useRef<HTMLInputElement>(null);
  const mapsRef = useRef<HTMLInputElement>(null);
  const instagramRef = useRef<HTMLInputElement>(null);
  const facebookRef = useRef<HTMLInputElement>(null);
  const siteRef = useRef<HTMLInputElement>(null);
  const historyRef = useRef<HTMLTextAreaElement>(null);

  // Inicializar os valores dos inputs (funcionalidade original)
  useEffect(() => {
    if (nameRef.current) nameRef.current.value = companyName;
    if (locationRef.current) locationRef.current.value = companyLocation;
    if (addressRef.current) addressRef.current.value = companyAddress;
    if (phoneFixedRef.current) phoneFixedRef.current.value = companyPhoneFixed;
    if (whatsAppRef.current) whatsAppRef.current.value = companyWhatsApp;
    if (mapsRef.current) mapsRef.current.value = companyMaps;
    if (instagramRef.current) instagramRef.current.value = companyInstagram;
    if (facebookRef.current) facebookRef.current.value = companyFacebook;
    if (siteRef.current) siteRef.current.value = companySite;
    if (historyRef.current) historyRef.current.value = companyHistory;
  }, [companyName, companyLocation, companyAddress, companyPhoneFixed, companyWhatsApp,
      companyMaps, companyInstagram, companyFacebook, companySite, companyHistory]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className={`block text-sm font-medium mb-1 ${
            isDark ? 'text-gray-300' : 'text-gray-700'
          }`}>
            <div className="flex items-center gap-2">
              <Building className={`w-4 h-4 ${
                isDark ? 'text-gray-400' : 'text-gray-500'
              }`} />
              <span>Nome da empresa</span>
            </div>
          </label>
          <Input
            ref={nameRef}
            type="text"
            placeholder="Ex: Empresa de serviços Sorrisos"
            defaultValue={companyName}
            onBlur={() => nameRef.current && setCompanyName(nameRef.current.value)}
          />
        </div>

        <div>
          <label className={`block text-sm font-medium mb-1 ${
            isDark ? 'text-gray-300' : 'text-gray-700'
          }`}>
            <div className="flex items-center gap-2">
              <MapPin className={`w-4 h-4 ${
                isDark ? 'text-gray-400' : 'text-gray-500'
              }`} />
              <span>Localização</span>
            </div>
          </label>
          <Input
            ref={locationRef}
            type="text"
            placeholder="Ex: São Paulo, SP"
            defaultValue={companyLocation}
            onBlur={() => locationRef.current && setCompanyLocation(locationRef.current.value)}
          />
        </div>
      </div>

      <div>
        <label className={`block text-sm font-medium mb-1 ${
          isDark ? 'text-gray-300' : 'text-gray-700'
        }`}>
          <div className="flex items-center gap-2">
            <Map className={`w-4 h-4 ${
              isDark ? 'text-gray-400' : 'text-gray-500'
            }`} />
            <span>Endereço completo</span>
          </div>
        </label>
        <Input
          ref={addressRef}
          type="text"
          placeholder="Ex: Rua dos Dentes, 123 - Jardim Bucal"
          defaultValue={companyAddress}
          onBlur={() => addressRef.current && setCompanyAddress(addressRef.current.value)}
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className={`block text-sm font-medium mb-1 ${
            isDark ? 'text-gray-300' : 'text-gray-700'
          }`}>
            <div className="flex items-center gap-2">
              <Phone className={`w-4 h-4 ${
                isDark ? 'text-gray-400' : 'text-gray-500'
              }`} />
              <span>Telefone fixo</span>
            </div>
          </label>
          <Input
            ref={phoneFixedRef}
            type="tel"
            placeholder="Ex: (11) 3333-4444"
            defaultValue={companyPhoneFixed}
            onBlur={() => phoneFixedRef.current && setCompanyPhoneFixed(phoneFixedRef.current.value)}
          />
        </div>

        <div>
          <label className={`block text-sm font-medium mb-1 ${
            isDark ? 'text-gray-300' : 'text-gray-700'
          }`}>
            <div className="flex items-center gap-2">
              <MessageCircle className={`w-4 h-4 ${
                isDark ? 'text-gray-400' : 'text-gray-500'
              }`} />
              <span>WhatsApp</span>
            </div>
          </label>
          <Input
            ref={whatsAppRef}
            type="tel"
            placeholder="Ex: (11) 98765-4321"
            defaultValue={companyWhatsApp}
            onBlur={() => whatsAppRef.current && setCompanyWhatsApp(whatsAppRef.current.value)}
          />
        </div>
      </div>

      <h3 className={`font-medium mt-6 mb-3 flex items-center gap-2 ${
        isDark ? 'text-gray-200' : 'text-gray-800'
      }`}>
        <Globe className="w-5 h-5 text-brand" />
        <span>Presença Digital</span>
      </h3>

      <div className={`grid grid-cols-1 md:grid-cols-2 gap-4 p-4 rounded-2xl border ${
        isDark
          ? 'bg-gray-700/50 border-gray-600'
          : 'bg-gray-50 border-gray-200'
      }`}>
        <div>
          <label className={`block text-sm font-medium mb-1 ${
            isDark ? 'text-gray-300' : 'text-gray-700'
          }`}>
            <div className="flex items-center gap-2">
              <Map className={`w-4 h-4 ${
                isDark ? 'text-gray-400' : 'text-gray-500'
              }`} />
              <span>Link do Google Maps</span>
            </div>
          </label>
          <Input
            ref={mapsRef}
            type="text"
            placeholder="https://goo.gl/maps/..."
            defaultValue={companyMaps}
            onBlur={() => mapsRef.current && setCompanyMaps(mapsRef.current.value)}
          />
        </div>

        <div>
          <label className={`block text-sm font-medium mb-1 ${
            isDark ? 'text-gray-300' : 'text-gray-700'
          }`}>
            <div className="flex items-center gap-2">
              <Instagram className={`w-4 h-4 ${
                isDark ? 'text-gray-400' : 'text-gray-500'
              }`} />
              <span>Instagram (URL)</span>
            </div>
          </label>
          <Input
            ref={instagramRef}
            type="text"
            placeholder="https://instagram.com/..."
            defaultValue={companyInstagram}
            onBlur={() => instagramRef.current && setCompanyInstagram(instagramRef.current.value)}
          />
        </div>

        <div>
          <label className={`block text-sm font-medium mb-1 ${
            isDark ? 'text-gray-300' : 'text-gray-700'
          }`}>
            <div className="flex items-center gap-2">
              <Facebook className={`w-4 h-4 ${
                isDark ? 'text-gray-400' : 'text-gray-500'
              }`} />
              <span>Facebook (URL)</span>
            </div>
          </label>
          <Input
            ref={facebookRef}
            type="text"
            placeholder="https://facebook.com/..."
            defaultValue={companyFacebook}
            onBlur={() => facebookRef.current && setCompanyFacebook(facebookRef.current.value)}
          />
        </div>

        <div>
          <label className={`block text-sm font-medium mb-1 ${
            isDark ? 'text-gray-300' : 'text-gray-700'
          }`}>
            <div className="flex items-center gap-2">
              <Globe className={`w-4 h-4 ${
                isDark ? 'text-gray-400' : 'text-gray-500'
              }`} />
              <span>Site (URL)</span>
            </div>
          </label>
          <Input
            ref={siteRef}
            type="text"
            placeholder="https://..."
            defaultValue={companySite}
            onBlur={() => siteRef.current && setCompanySite(siteRef.current.value)}
          />
        </div>
      </div>

      <div className="mt-4">
        <label className={`block text-sm font-medium mb-1 ${
          isDark ? 'text-gray-300' : 'text-gray-700'
        }`}>
          <div className="flex items-center gap-2">
            <FileText className={`w-4 h-4 ${
              isDark ? 'text-gray-400' : 'text-gray-500'
            }`} />
            <span>História da empresa</span>
          </div>
        </label>
        <Textarea
          ref={historyRef}
          rows={4}
          placeholder="Conte um pouco sobre a história da sua empresa..."
          defaultValue={companyHistory}
          onBlur={() => historyRef.current && setCompanyHistory(historyRef.current.value)}
        />
      </div>
    </div>
  );
};

export default CompanyInfoForm;