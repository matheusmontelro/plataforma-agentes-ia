import React, { useState, useEffect } from 'react';
import { BarChart3, TrendingUp, Users, Star, Calendar } from 'lucide-react';
import { useTheme } from '../../contexts/ThemeContext.tsx';
import { getNPSDashboardMetrics, NPSDashboardMetrics } from '../../services/api.ts';
import { BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

interface NPSSectionProps {
  startDate: string;
  endDate: string;
}

// Cores para o gráfico
const COLORS = {
  promoters: '#10b981',    // Verde
  passives: '#f59e0b',     // Amarelo
  detractors: '#ef4444'    // Vermelho
};

const NPSSection: React.FC<NPSSectionProps> = ({ startDate, endDate }) => {
  const { isDark } = useTheme();
  const [metrics, setMetrics] = useState<NPSDashboardMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedCampaign, setSelectedCampaign] = useState<string>('');

  useEffect(() => {
    loadMetrics();
  }, [startDate, endDate, selectedCampaign]);

  const loadMetrics = async () => {
    try {
      setLoading(true);
      const data = await getNPSDashboardMetrics(
        startDate,
        endDate,
        selectedCampaign || undefined
      );
      setMetrics(data);
    } catch (error) {
      console.error('Erro ao carregar métricas NPS:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="animate-pulse">
        <div className={`h-96 rounded-lg ${isDark ? 'bg-gray-700' : 'bg-gray-200'}`}></div>
      </div>
    );
  }

  if (!metrics) {
    return <div className={isDark ? 'text-gray-300' : 'text-gray-800'}>Erro ao carregar métricas NPS</div>;
  }

  // Preparar dados para os gráficos - filtrar apenas categorias com valores > 0
  const distributionData = [
    { name: 'Promotores', value: metrics.metrics.distribution.promoters, color: COLORS.promoters },
    { name: 'Neutros', value: metrics.metrics.distribution.passives, color: COLORS.passives },
    { name: 'Detratores', value: metrics.metrics.distribution.detractors, color: COLORS.detractors }
  ].filter(item => item.value > 0);

  const scoreData = Object.entries(metrics.score_distribution).map(([score, count]) => ({
    score: `${score} ⭐`,
    count
  }));


  return (
    <div className="space-y-6">
      {/* Grid de métricas estilo HubSpot - Mobile: apenas os 3 cards principais */}
      <div className="mb-6 grid grid-cols-3 gap-2 sm:gap-4">
        <div className="rounded-xl bg-rose-50 p-3 sm:p-4 text-rose-700 dark:bg-rose-900/20 dark:text-rose-300">
          <p className="text-xs font-medium uppercase tracking-wide">Detratores</p>
          <p className="text-xl sm:text-2xl font-bold mt-1">{Math.round((metrics.metrics.distribution.detractors / (metrics.metrics.distribution.detractors + metrics.metrics.distribution.passives + metrics.metrics.distribution.promoters || 1)) * 100)}%</p>
          <p className="text-xs text-rose-600 dark:text-rose-400 mt-1 hidden sm:block">{metrics.metrics.distribution.detractors} respostas</p>
        </div>
        <div className="rounded-xl bg-amber-50 p-3 sm:p-4 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300">
          <p className="text-xs font-medium uppercase tracking-wide">Neutros</p>
          <p className="text-xl sm:text-2xl font-bold mt-1">{Math.round((metrics.metrics.distribution.passives / (metrics.metrics.distribution.detractors + metrics.metrics.distribution.passives + metrics.metrics.distribution.promoters || 1)) * 100)}%</p>
          <p className="text-xs text-amber-600 dark:text-amber-400 mt-1 hidden sm:block">{metrics.metrics.distribution.passives} respostas</p>
        </div>
        <div className="rounded-xl bg-emerald-50 p-3 sm:p-4 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300">
          <p className="text-xs font-medium uppercase tracking-wide">Promotores</p>
          <p className="text-xl sm:text-2xl font-bold mt-1">{Math.round((metrics.metrics.distribution.promoters / (metrics.metrics.distribution.detractors + metrics.metrics.distribution.passives + metrics.metrics.distribution.promoters || 1)) * 100)}%</p>
          <p className="text-xs text-emerald-600 dark:text-emerald-400 mt-1 hidden sm:block">{metrics.metrics.distribution.promoters} respostas</p>
        </div>
      </div>

      {/* NPS Score centralizado estilo HubSpot */}
      <div className="text-center mb-6">
        <div className={`text-sm font-medium ${isDark ? 'text-gray-300' : 'text-gray-600'}`}>NPS atual</div>
        <div className={`text-4xl font-bold mt-1 ${
          metrics.metrics.nps_score >= 50 ? 'text-emerald-600' :
          metrics.metrics.nps_score >= 0 ? 'text-amber-600' : 'text-rose-600'
        }`}>
          {metrics.metrics.nps_score}
        </div>
        <div className={`text-xs mt-1 ${isDark ? 'text-gray-400' : 'text-gray-500'}`}>
          Taxa de resposta: {metrics.metrics.response_rate}% • Média: {metrics.metrics.average_score.toFixed(1)} ⭐ • Total: {metrics.metrics.total_sent}
        </div>
      </div>

      {/* Gráficos */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Distribuição NPS */}
        <div className={`rounded-lg shadow-sm border p-6 ${
          isDark
            ? 'bg-brand border-gray-600 text-white'
            : 'bg-white border-gray-100 text-gray-800'
        }`}>
          <h3 className={`text-lg font-semibold mb-4 ${isDark ? 'text-gray-200' : 'text-gray-800'}`}>Distribuição NPS</h3>
          {distributionData.length > 0 ? (
            <div className="space-y-4">
              <ResponsiveContainer width="100%" height={250}>
                <PieChart>
                  <Pie
                    data={distributionData}
                    cx="50%"
                    cy="50%"
                    outerRadius={80}
                    fill="#8884d8"
                    dataKey="value"
                    label={false}
                  >
                    {distributionData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value, name) => [value, name]}
                    labelFormatter={() => ''}
                    contentStyle={{
                      backgroundColor: isDark ? '#020323' : '#FFFFFF',
                      border: `1px solid ${isDark ? '#4B5563' : '#E5E7EB'}`,
                      borderRadius: '8px',
                      color: isDark ? '#f7f7f7' : '#020323'
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>

              {/* Legenda customizada */}
              <div className="flex flex-wrap justify-center gap-4">
                {distributionData.map((entry, index) => (
                  <div key={index} className="flex items-center gap-2">
                    <div
                      className="w-3 h-3 rounded-full"
                      style={{ backgroundColor: entry.color }}
                    ></div>
                    <span className={`text-sm ${isDark ? 'text-gray-300' : 'text-gray-700'}`}>
                      {entry.name}: {entry.value} ({((entry.value / distributionData.reduce((sum, item) => sum + item.value, 0)) * 100).toFixed(0)}%)
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className={`flex items-center justify-center h-64 ${isDark ? 'text-gray-400' : 'text-gray-500'}`}>
              <div className="text-center">
                <Star className={`h-12 w-12 mx-auto mb-2 ${isDark ? 'text-gray-500' : 'text-gray-300'}`} />
                <p>Nenhum dado de NPS disponível no período</p>
              </div>
            </div>
          )}
        </div>

        {/* Distribuição por Score - Estilo HubSpot */}
        <div className={`rounded-lg shadow-sm border p-6 ${
          isDark
            ? 'bg-brand border-gray-600 text-white'
            : 'bg-white border-gray-100 text-gray-800'
        }`}>
          <h3 className={`text-lg font-semibold mb-4 ${isDark ? 'text-gray-200' : 'text-gray-800'}`}>Distribuição por Nota</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={scoreData} margin={{ left: 8, right: 8, top: 8, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={isDark ? "#374151" : "#e2e8f0"} />
              <XAxis
                dataKey="score"
                tick={{ fontSize: 12, fill: isDark ? '#9CA3AF' : '#6B7280' }}
                axisLine={{ stroke: isDark ? '#4B5563' : '#E5E7EB' }}
                tickLine={{ stroke: isDark ? '#4B5563' : '#E5E7EB' }}
              />
              <YAxis
                tick={{ fontSize: 12, fill: isDark ? '#9CA3AF' : '#6B7280' }}
                axisLine={{ stroke: isDark ? '#4B5563' : '#E5E7EB' }}
                tickLine={{ stroke: isDark ? '#4B5563' : '#E5E7EB' }}
              />
              <Tooltip
                formatter={(value: any) => [`${value} respostas`, 'Quantidade']}
                contentStyle={{
                  backgroundColor: isDark ? '#020323' : '#FFFFFF',
                  border: `1px solid ${isDark ? '#4B5563' : '#E5E7EB'}`,
                  borderRadius: '8px',
                  color: isDark ? '#f7f7f7' : '#020323'
                }}
              />
              <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                {scoreData.map((entry, index) => {
                  // Extrair o número da nota do formato "X ⭐"
                  const scoreNum = parseInt(entry.score.split(' ')[0]);
                  return (
                    <Cell key={`cell-${index}`} fill={
                      scoreNum <= 2 ? "#ef4444" :  // Vermelho para detratores (1-2)
                      scoreNum <= 3 ? "#f59e0b" :  // Amarelo para neutros (3)
                      "#22c55e"                    // Verde para promotores (4-5)
                    } />
                  );
                })}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <p className="text-[11px] text-gray-500 dark:text-gray-400 text-center mt-2">
            1–2: detratores • 3: neutros • 4–5: promotores
          </p>
        </div>
      </div>


      {/* Tabela de Campanhas */}
      {metrics.campaigns.length > 0 && (
        <div className={`rounded-lg shadow-sm border p-6 ${
          isDark
            ? 'bg-brand border-gray-600 text-white'
            : 'bg-white border-gray-100 text-gray-800'
        }`}>
          <div className="flex justify-between items-center mb-4">
            <h3 className={`text-lg font-semibold ${isDark ? 'text-gray-200' : 'text-gray-800'}`}>Campanhas</h3>
            <select
              value={selectedCampaign}
              onChange={(e) => setSelectedCampaign(e.target.value)}
              className={`px-3 py-1 border rounded-md text-sm transition-colors ${
                isDark
                  ? 'border-gray-600 bg-gray-700 text-gray-200'
                  : 'border-gray-300 bg-white text-gray-800'
              }`}
            >
              <option value="">Todas as campanhas</option>
              {metrics.campaigns.map(campaign => (
                <option key={campaign.name} value={campaign.name}>
                  {campaign.name}
                </option>
              ))}
            </select>
          </div>

          <div className="overflow-x-auto">
            <table className={`min-w-full divide-y ${isDark ? 'divide-gray-600' : 'divide-gray-200'}`}>
              <thead className={isDark ? 'bg-gray-700/50' : 'bg-gray-50'}>
                <tr>
                  <th className={`px-6 py-3 text-left text-xs font-medium uppercase tracking-wider ${
                    isDark ? 'text-gray-300' : 'text-gray-500'
                  }`}>
                    Campanha
                  </th>
                  <th className={`px-6 py-3 text-left text-xs font-medium uppercase tracking-wider ${
                    isDark ? 'text-gray-300' : 'text-gray-500'
                  }`}>
                    Enviadas
                  </th>
                  <th className={`px-6 py-3 text-left text-xs font-medium uppercase tracking-wider ${
                    isDark ? 'text-gray-300' : 'text-gray-500'
                  }`}>
                    Respondidas
                  </th>
                  <th className={`px-6 py-3 text-left text-xs font-medium uppercase tracking-wider ${
                    isDark ? 'text-gray-300' : 'text-gray-500'
                  }`}>
                    Taxa de Resposta
                  </th>
                  <th className={`px-6 py-3 text-left text-xs font-medium uppercase tracking-wider ${
                    isDark ? 'text-gray-300' : 'text-gray-500'
                  }`}>
                    Média
                  </th>
                </tr>
              </thead>
              <tbody className={`divide-y ${
                isDark
                  ? 'bg-brand divide-gray-600'
                  : 'bg-white divide-gray-200'
              }`}>
                {metrics.campaigns.map((campaign) => (
                  <tr key={campaign.name}>
                    <td className={`px-6 py-4 whitespace-nowrap text-sm font-medium ${
                      isDark ? 'text-gray-200' : 'text-gray-900'
                    }`}>
                      {campaign.name}
                    </td>
                    <td className={`px-6 py-4 whitespace-nowrap text-sm ${
                      isDark ? 'text-gray-400' : 'text-gray-500'
                    }`}>
                      {campaign.total}
                    </td>
                    <td className={`px-6 py-4 whitespace-nowrap text-sm ${
                      isDark ? 'text-gray-400' : 'text-gray-500'
                    }`}>
                      {campaign.answered}
                    </td>
                    <td className={`px-6 py-4 whitespace-nowrap text-sm ${
                      isDark ? 'text-gray-400' : 'text-gray-500'
                    }`}>
                      {campaign.response_rate}%
                    </td>
                    <td className={`px-6 py-4 whitespace-nowrap text-sm ${
                      isDark ? 'text-gray-400' : 'text-gray-500'
                    }`}>
                      <div className="flex items-center">
                        <span className="mr-1">{campaign.avg_score.toFixed(1)}</span>
                        <Star className="h-4 w-4 text-yellow-400 fill-current" />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

export default NPSSection;