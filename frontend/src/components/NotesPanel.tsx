import React, { useState, useEffect } from 'react';
import {
  StickyNote,
  Plus,
  Edit2,
  Trash2,
  User,
  XCircle,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import { format, formatDistanceToNow, parseISO } from 'date-fns';
import { ptBR } from 'date-fns/locale';
import api from '../services/api.ts';
import { useTheme } from '../contexts/ThemeContext.tsx';
import {
  AgentiveConfirmModal,
  AgentiveEmptyState,
  agentiveIconButtonClass,
  agentiveInputClass,
  agentivePanelClass,
  agentivePrimaryButtonClass,
  agentiveSecondaryButtonClass,
} from './AgentiveUI.tsx';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

interface NotesPanelProps {
  contactId: string;  // Accept phone number
  contactName: string;
  contactPhone: string;
  companyId: number;
  onClose?: () => void;
}

interface Note {
  id: number;
  contact_id: number;
  contact_name: string;
  contact_phone: string;
  content: string;
  created_at: string;
  updated_at: string;
  created_by: {
    id: number;
    name: string;
    email: string;
    type: string;
  };
}

interface NoteFormData {
  content: string;
}

const NotesPanel: React.FC<NotesPanelProps> = ({
  contactId,
  contactName,
  contactPhone,
  companyId,
  onClose
}) => {
  const { isDark } = useTheme();
  const [notes, setNotes] = useState<Note[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingNote, setEditingNote] = useState<Note | null>(null);
  const [expandedNotes, setExpandedNotes] = useState<Set<number>>(new Set());
  const [noteToDelete, setNoteToDelete] = useState<number | null>(null);

  const [formData, setFormData] = useState<NoteFormData>({
    content: ''
  });

  useEffect(() => {
    fetchNotes();
  }, [contactId]);

  // Handle escape key to close modal and prevent body scroll
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && showForm) {
        setShowForm(false);
        setEditingNote(null);
        resetForm();
      }
    };

    if (showForm) {
      document.addEventListener('keydown', handleEscape);
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = 'unset';
    }

    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = 'unset';
    };
  }, [showForm]);

  const fetchNotes = async () => {
    try {
      setLoading(true);
      const response = await api.get(`/api/contacts/${contactId}/notes`);
      setNotes(response.data);
    } catch (error) {
      console.error('Error fetching notes:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!formData.content.trim()) {
      return;
    }

    try {
      if (editingNote) {
        await api.put(`/api/notes/${editingNote.id}`, formData);
      } else {
        await api.post(`/api/contacts/${contactId}/notes`, formData);
      }

      fetchNotes();
      setShowForm(false);
      setEditingNote(null);
      resetForm();
    } catch (error) {
      console.error('Error saving note:', error);
    }
  };

  const handleDelete = async (noteId: number) => {
    setNoteToDelete(noteId);
  };

  const confirmDelete = async () => {
    if (!noteToDelete) return;

    try {
      await api.delete(`/api/notes/${noteToDelete}`);
      fetchNotes();
    } catch (error) {
      console.error('Error deleting note:', error);
    } finally {
      setNoteToDelete(null);
    }
  };

  const resetForm = () => {
    setFormData({
      content: ''
    });
  };

  const formatNoteDate = (dateString: string) => {
    const date = parseISO(dateString);

    return {
      absolute: format(date, "dd/MM/yyyy 'às' HH:mm", { locale: ptBR }),
      relative: formatDistanceToNow(date, { locale: ptBR, addSuffix: true })
    };
  };

  return (
    <div className={agentivePanelClass(isDark, 'mx-auto max-w-4xl p-4 sm:p-6')}>
      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-xl font-semibold">Anotações</h2>
          <p className={cx('mt-1 text-sm', isDark ? 'text-white/55' : 'text-brand/55')}>
            {contactName} • {contactPhone}
          </p>
        </div>

        <button
          onClick={() => setShowForm(true)}
          className={agentivePrimaryButtonClass()}
        >
          <Plus className="h-4 w-4" />
          Nova Anotação
        </button>
      </div>

      {/* Notes List */}
      {loading ? (
        <div className="text-center py-8">
          <div className={cx('mx-auto h-8 w-8 animate-spin rounded-full border-2 border-t-transparent', isDark ? 'border-white/35' : 'border-brand/35')}></div>
        </div>
      ) : notes.length === 0 ? (
        <AgentiveEmptyState
          icon={StickyNote}
          title="Nenhuma anotação"
          description="Registre observações importantes deste atendimento."
        />
      ) : (
        <div className="space-y-3">
          {notes.map(note => {
            const isExpanded = expandedNotes.has(note.id);
            const dateFormat = formatNoteDate(note.created_at);
            const wasEdited = note.updated_at !== note.created_at;

            return (
              <div
                key={note.id}
                className={cx('rounded-2xl border p-4 transition-all', isDark ? 'border-white/10 bg-white/[0.04] hover:bg-white/[0.07]' : 'border-brand/10 bg-white hover:bg-brand-canvas')}
              >
                <div className="flex items-start gap-3">
                  {/* Note Icon */}
                  <div className="mt-1">
                    <StickyNote className={cx('h-4 w-4', isDark ? 'text-white/55' : 'text-brand/55')} />
                  </div>

                  {/* Main Content */}
                  <div className="flex-1">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        {/* Content Preview */}
                        <div className="mb-2">
                          <p className={cx(
                            !isExpanded && note.content.length > 150 ? 'line-clamp-3' : ''
                          , isDark ? 'text-white/80' : 'text-brand/80')}>
                            {isExpanded || note.content.length <= 150
                              ? note.content
                              : `${note.content.substring(0, 150)}...`}
                          </p>
                        </div>

                        {/* Metadata */}
                        <div className={cx('mb-2 flex items-center gap-3 text-sm', isDark ? 'text-white/45' : 'text-brand/45')}>
                          <div className="flex items-center gap-1">
                            <User className="h-3 w-3" />
                            <span>{note.created_by.name}</span>
                          </div>
                          <span>•</span>
                          <span title={dateFormat.absolute}>
                            {dateFormat.relative}
                          </span>
                          {wasEdited && (
                            <>
                              <span>•</span>
                              <span className="italic">editado</span>
                            </>
                          )}
                        </div>
                      </div>

                      {/* Actions */}
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => {
                            setEditingNote(note);
                            setFormData({
                              content: note.content
                            });
                            setShowForm(true);
                          }}
                          className="p-1 hover:bg-gray-100 rounded transition-colors"
                          title="Editar anotação"
                        >
                          <Edit2 className="h-4 w-4 text-gray-600" />
                        </button>

                        <button
                          onClick={() => handleDelete(note.id)}
                          className="p-1 hover:bg-gray-100 rounded transition-colors"
                          title="Excluir anotação"
                        >
                          <Trash2 className="h-4 w-4 text-red-600" />
                        </button>

                        {note.content.length > 150 && (
                          <button
                            onClick={() => {
                              if (isExpanded) {
                                setExpandedNotes(prev => {
                                  const next = new Set(prev);
                                  next.delete(note.id);
                                  return next;
                                });
                              } else {
                                setExpandedNotes(prev => new Set(prev).add(note.id));
                              }
                            }}
                            className="p-1 hover:bg-gray-100 rounded transition-colors"
                            title={isExpanded ? "Mostrar menos" : "Mostrar mais"}
                          >
                            {isExpanded ? (
                              <ChevronUp className="h-4 w-4" />
                            ) : (
                              <ChevronDown className="h-4 w-4" />
                            )}
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Expanded Content */}
                    {isExpanded && wasEdited && (
                      <div className="mt-3 pt-3 border-t border-gray-200">
                        <div className="text-sm text-gray-500">
                          <span>Última edição: </span>
                          <span>{formatNoteDate(note.updated_at).absolute}</span>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Note Form Modal */}
      {showForm && (
        <div
                className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-brand/55 p-2 backdrop-blur-sm sm:p-4"
          onClick={(e) => {
            if (e.target === e.currentTarget) {
              setShowForm(false);
              setEditingNote(null);
              resetForm();
            }
          }}
        >
          <div className={cx('mx-auto my-4 flex max-h-[calc(100vh-2rem)] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border shadow-2xl sm:my-8 sm:max-h-[calc(100vh-4rem)]', isDark ? 'border-white/10 bg-brand text-white' : 'border-brand/10 bg-white text-brand')}>
            {/* Modal Header - Fixed */}
            <div className={cx('flex flex-shrink-0 items-center justify-between border-b p-4 sm:p-6', isDark ? 'border-white/10' : 'border-brand/10')}>
              <h3 className="text-lg font-semibold">
                {editingNote ? 'Editar Anotação' : 'Nova Anotação'}
              </h3>
              <button
                type="button"
                onClick={() => {
                  setShowForm(false);
                  setEditingNote(null);
                  resetForm();
                }}
                className={agentiveIconButtonClass(isDark)}
                title="Fechar"
              >
                <XCircle className="h-5 w-5" />
              </button>
            </div>

            {/* Modal Content - Scrollable */}
            <div className="flex-1 overflow-y-auto p-4 sm:p-6">
              <form id="note-form" onSubmit={handleSubmit}>
                {/* Content */}
                <div className="mb-6">
                  <label className={cx('mb-2 block text-sm font-medium', isDark ? 'text-white/70' : 'text-brand/70')}>
                    Conteúdo da Anotação
                  </label>
                  <textarea
                    value={formData.content}
                    onChange={(e) => setFormData({ ...formData, content: e.target.value })}
                    className={agentiveInputClass(isDark, 'resize-none px-3 py-3')}
                    rows={8}
                    placeholder="Digite sua anotação aqui..."
                    required
                  />
                  <div className={cx('mt-1 text-xs', isDark ? 'text-white/45' : 'text-brand/45')}>
                    {formData.content.length} caracteres
                  </div>
                </div>
              </form>
            </div>

            {/* Modal Footer - Fixed */}
            <div className={cx('flex flex-shrink-0 gap-3 border-t p-4 sm:p-6', isDark ? 'border-white/10' : 'border-brand/10')}>
              <button
                type="button"
                onClick={() => {
                  setShowForm(false);
                  setEditingNote(null);
                  resetForm();
                }}
                className={agentiveSecondaryButtonClass(isDark, 'flex-1')}
              >
                Cancelar
              </button>
              <button
                type="submit"
                form="note-form"
                className={agentivePrimaryButtonClass('flex-1')}
                disabled={!formData.content.trim()}
              >
                {editingNote ? 'Salvar' : 'Criar'}
              </button>
            </div>
          </div>
        </div>
      )}

      <AgentiveConfirmModal
        isOpen={noteToDelete !== null}
        title="Excluir anotacao?"
        message="Esta anotacao sera removida do historico do contato."
        confirmText="Excluir anotacao"
        cancelText="Cancelar"
        variant="danger"
        onClose={() => setNoteToDelete(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
};

export default NotesPanel;
