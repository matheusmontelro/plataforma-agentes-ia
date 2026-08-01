import React from 'react';
import { DragDropContext, Droppable, Draggable, DropResult } from '@hello-pangea/dnd';
import { MoreVertical, Plus } from 'lucide-react';
import { Lead } from '../services/api.ts';

// Interfaces for Kanban
export interface KanbanStage {
  id: number;
  name: string;
  color: string;
  order_index: number;
}

export interface KanbanData {
  stages: KanbanStage[];
  leads: Lead[]; // We will filter leads by stage_id in the component
}

interface KanbanBoardProps {
  stages: KanbanStage[];
  leads: Lead[];
  onDragEnd: (result: DropResult) => void;
  onLeadClick: (lead: Lead) => void;
}

const KanbanBoard: React.FC<KanbanBoardProps> = ({ stages, leads, onDragEnd, onLeadClick }) => {

  // Helper to get leads for a specific stage
  const getLeadsForStage = (stageId: number) => {
    return leads.filter(lead => (lead as any).stage_id === stageId);
  };

  return (
    <DragDropContext onDragEnd={onDragEnd}>
      <div className="flex h-full overflow-x-auto pb-4 space-x-4">
        {stages.map((stage) => (
          <div
            key={stage.id}
            className="flex-shrink-0 w-80 flex flex-col bg-gray-50 rounded-lg border border-gray-200 max-h-full"
          >
            {/* Column Header */}
            <div className="p-3 border-b border-gray-200 flex justify-between items-center bg-white rounded-t-lg">
              <div className="flex items-center">
                <div
                  className="w-3 h-3 rounded-full mr-2"
                  style={{ backgroundColor: stage.color || '#cbd5e1' }}
                />
                <h3 className="font-medium text-gray-700 text-sm">{stage.name}</h3>
                <span className="ml-2 bg-gray-100 text-gray-600 text-xs px-2 py-0.5 rounded-full">
                  {getLeadsForStage(stage.id).length}
                </span>
              </div>
              <button className="text-gray-400 hover:text-gray-600">
                <MoreVertical className="w-4 h-4" />
              </button>
            </div>

            {/* Droppable Area */}
            <Droppable droppableId={String(stage.id)}>
              {(provided, snapshot) => (
                <div
                  ref={provided.innerRef}
                  {...provided.droppableProps}
                  className={`flex-1 p-2 overflow-y-auto min-h-[100px] transition-colors ${snapshot.isDraggingOver ? 'bg-blue-50' : ''
                    }`}
                >
                  {getLeadsForStage(stage.id).map((lead, index) => (
                    <Draggable key={lead.id} draggableId={String(lead.id)} index={index}>
                      {(provided, snapshot) => (
                        <div
                          ref={provided.innerRef}
                          {...provided.draggableProps}
                          {...provided.dragHandleProps}
                          onClick={() => onLeadClick(lead)}
                          className={`bg-white p-3 rounded border border-gray-200 shadow-sm mb-2 hover:shadow-md transition-shadow cursor-pointer ${snapshot.isDragging ? 'shadow-lg ring-2 ring-blue-400 rotate-2' : ''
                            }`}
                          style={{
                            ...provided.draggableProps.style,
                          }}
                        >
                          <div className="flex justify-between items-start mb-1">
                            <span className="text-xs font-medium text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded">
                              #{lead.id}
                            </span>
                            {lead.data_entrada && (
                              <span className="text-[10px] text-gray-400">
                                {new Date(lead.data_entrada).toLocaleDateString('pt-BR')}
                              </span>
                            )}
                          </div>
                          <h4 className="text-sm font-medium text-gray-900 mb-1 truncate">
                            {lead.name || 'Sem nome'}
                          </h4>
                          <div className="flex items-center text-xs text-gray-500 mb-2">
                            <span className="truncate">{lead.phone}</span>
                          </div>

                          {/* Tags/Badges area */}
                          <div className="flex flex-wrap gap-1 mt-2">
                            {/* Example tags - can be dynamic */}
                            {lead.source_id && (
                              <span className="text-[10px] bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded truncate max-w-full">
                                {lead.source_id}
                              </span>
                            )}
                          </div>
                        </div>
                      )}
                    </Draggable>
                  ))}
                  {provided.placeholder}
                </div>
              )}
            </Droppable>

            {/* Column Footer (Add Button) */}
            {/* <div className="p-2 border-t border-gray-200">
              <button className="w-full py-1.5 flex items-center justify-center text-gray-500 hover:bg-gray-100 rounded text-sm transition-colors">
                <Plus className="w-4 h-4 mr-1" />
                Adicionar
              </button>
            </div> */}
          </div>
        ))}
      </div>
    </DragDropContext>
  );
};

export default KanbanBoard;
