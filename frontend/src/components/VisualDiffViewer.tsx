import React, { useEffect, useRef, useState } from 'react'
import { OpenSheetMusicDisplay } from 'opensheetmusicdisplay'
import { ZoomIn, ZoomOut, ChevronLeft, ChevronRight, Music, Piano, Users, Compass, RotateCcw } from 'lucide-react'
import type { JobData } from '../types'

interface VisualDiffViewerProps {
  job: JobData
  selectedMeasureNumber: number | null
  onSelectMeasure: (measureNumber: number) => void
  currentPlayingMeasure?: number
  onSoloVocals?: () => void
  onSoloPiano?: () => void
  onResetMuteSolo?: () => void
}

export const VisualDiffViewer: React.FC<VisualDiffViewerProps> = ({
  job,
  selectedMeasureNumber,
  onSelectMeasure,
  currentPlayingMeasure,
  onSoloVocals,
  onSoloPiano,
  onResetMuteSolo
}) => {
  const [currentPage, setCurrentPage] = useState<number>(1)
  const [zoomLevel, setZoomLevel] = useState<number>(1.0)
  const [scorePartition, setScorePartition] = useState<'full' | 'vocals' | 'piano'>('full')
  const [jumpMeasureInput, setJumpMeasureInput] = useState<string>('')
  const osmdContainerRef = useRef<HTMLDivElement | null>(null)
  const osmdInstanceRef = useRef<OpenSheetMusicDisplay | null>(null)
  const [isOsmdLoaded, setIsOsmdLoaded] = useState<boolean>(false)

  const layoutData = job.layout_data
  const pageCount = job.page_count || 1
  const currentPageLayout = layoutData?.pages?.find(p => p.page_num === currentPage)
  const pageImageUrl = `/api/v1/jobs/${job.job_id}/files/layout/page_${currentPage}.png`

  // Initialize OSMD when score XML is compiled or partition changes
  useEffect(() => {
    if (!osmdContainerRef.current) return
    if (!job.decoder_result) return

    const xmlFilename =
      scorePartition === 'vocals'
        ? 'score_vocals.musicxml'
        : scorePartition === 'piano'
        ? 'score_piano.musicxml'
        : 'score.musicxml'

    const xmlUrl = `/api/v1/jobs/${job.job_id}/files/compiled/${xmlFilename}`

    const initOsmd = async () => {
      try {
        if (!osmdInstanceRef.current) {
          osmdInstanceRef.current = new OpenSheetMusicDisplay(osmdContainerRef.current!, {
            autoResize: true,
            backend: 'svg',
            drawTitle: true,
            drawSubtitle: true,
            drawComposer: true,
            drawPartNames: true,
            drawMeasureNumbers: true,
            drawCredits: false,
          })
        }

        const osmd = osmdInstanceRef.current
        await osmd.load(xmlUrl)
        osmd.zoom = zoomLevel
        osmd.render()
        setIsOsmdLoaded(true)
      } catch (err) {
        console.error('Error rendering MusicXML in OSMD:', err)
      }
    }

    initOsmd()
  }, [job.job_id, job.decoder_result, zoomLevel, scorePartition])

  // Move OSMD cursor when measure changes
  useEffect(() => {
    const targetMeasure = currentPlayingMeasure || selectedMeasureNumber
    if (osmdInstanceRef.current && isOsmdLoaded && targetMeasure) {
      try {
        const cursor = osmdInstanceRef.current.cursor
        if (cursor) {
          cursor.show()
          cursor.reset()
          while (!cursor.iterator.EndReached && cursor.iterator.CurrentMeasureIndex < targetMeasure - 1) {
            cursor.next()
          }
        }
      } catch (err) {
        // Safe catch
      }
    }
  }, [selectedMeasureNumber, currentPlayingMeasure, isOsmdLoaded])

  // Auto-flip PDF page when selected or playing measure is on another page
  useEffect(() => {
    const targetMeasure = currentPlayingMeasure || selectedMeasureNumber
    if (!targetMeasure || !layoutData?.systems) return

    const sysForMeasure = layoutData.systems.find((s: any) =>
      s.measures?.some((m: any) => m.measure_number === targetMeasure)
    )
    if (sysForMeasure && sysForMeasure.page_num && sysForMeasure.page_num !== currentPage) {
      setCurrentPage(sysForMeasure.page_num)
    }
  }, [selectedMeasureNumber, currentPlayingMeasure, layoutData, currentPage])

  const handleJumpMeasure = (e: React.FormEvent) => {
    e.preventDefault()
    const mNum = parseInt(jumpMeasureInput.trim(), 10)
    if (!isNaN(mNum) && mNum >= 1 && mNum <= (job.total_measures || 999)) {
      onSelectMeasure(mNum)
      setJumpMeasureInput('')
    }
  }

  const pageSystems = layoutData?.systems?.filter((s: any) => s.page_num === currentPage) || []

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl flex flex-col h-[670px]">
      {/* Top Header & Page Controls */}
      <div className="bg-slate-950/80 px-4 py-2.5 border-b border-slate-800 flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <span className="text-xs uppercase tracking-wider font-semibold text-sky-400">Visual Diff Studio</span>
          <span className="text-xs text-slate-500 font-mono hidden md:inline">Original PDF (Left) vs. Interactive OSMD (Right)</span>
        </div>

        {/* Partition Selector & Player Helpers */}
        <div className="flex items-center gap-2">
          {/* Partition Selector */}
          <div className="flex items-center gap-1 bg-slate-900 p-0.5 rounded-lg border border-slate-800 text-xs font-semibold">
            <button
              onClick={() => setScorePartition('full')}
              className={`flex items-center gap-1 px-2 py-1 rounded transition cursor-pointer ${
                scorePartition === 'full' ? 'bg-sky-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'
              }`}
              title="View full synchronized score (Vocals + Piano)"
            >
              <Music className="w-3 h-3" />
              <span>Full Score</span>
            </button>
            <button
              onClick={() => setScorePartition('vocals')}
              className={`flex items-center gap-1 px-2 py-1 rounded transition cursor-pointer ${
                scorePartition === 'vocals' ? 'bg-sky-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'
              }`}
              title="View vocal parts only (bracketed choir score)"
            >
              <Users className="w-3 h-3" />
              <span>Vocals Only</span>
            </button>
            <button
              onClick={() => setScorePartition('piano')}
              className={`flex items-center gap-1 px-2 py-1 rounded transition cursor-pointer ${
                scorePartition === 'piano' ? 'bg-sky-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'
              }`}
              title="View piano accompaniment only (2 staves with curly brace)"
            >
              <Piano className="w-3 h-3" />
              <span>Piano Only</span>
            </button>
          </div>

          {/* Jump to Measure Form */}
          <form onSubmit={handleJumpMeasure} className="flex items-center gap-1 bg-slate-900 px-2 py-1 rounded-md border border-slate-800 text-xs">
            <Compass className="w-3 h-3 text-slate-400" />
            <input
              type="number"
              min={1}
              max={job.total_measures || 999}
              placeholder="M#"
              value={jumpMeasureInput}
              onChange={(e) => setJumpMeasureInput(e.target.value)}
              className="w-12 bg-transparent text-white font-mono text-xs focus:outline-none placeholder:text-slate-600"
            />
            <button type="submit" className="text-[10px] uppercase font-bold text-sky-400 hover:text-sky-300 cursor-pointer">
              Go
            </button>
          </form>

          {/* Audio Solo Helpers */}
          {(onSoloVocals || onSoloPiano) && (
            <div className="flex items-center gap-1 bg-slate-900 px-1 py-1 rounded-md border border-slate-800 text-xs">
              {onSoloVocals && (
                <button
                  onClick={onSoloVocals}
                  className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-indigo-950 text-indigo-300 hover:bg-indigo-900 border border-indigo-800 cursor-pointer"
                  title="Solo all vocal parts (mute piano)"
                >
                  Solo Vocals
                </button>
              )}
              {onSoloPiano && (
                <button
                  onClick={onSoloPiano}
                  className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-950 text-emerald-300 hover:bg-emerald-900 border border-emerald-800 cursor-pointer"
                  title="Solo piano accompaniment (mute vocals)"
                >
                  Solo Piano
                </button>
              )}
              {onResetMuteSolo && (
                <button
                  onClick={onResetMuteSolo}
                  className="p-1 text-slate-400 hover:text-white cursor-pointer"
                  title="Reset all mutes & solos"
                >
                  <RotateCcw className="w-3 h-3" />
                </button>
              )}
            </div>
          )}

          {/* Page Nav */}
          <div className="flex items-center gap-1 bg-slate-900 px-2 py-1 rounded-md border border-slate-800 text-xs">
            <button
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              disabled={currentPage <= 1}
              className="p-1 hover:text-sky-400 disabled:opacity-30 cursor-pointer"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
            <span className="font-mono text-slate-300">Page {currentPage} / {pageCount}</span>
            <button
              onClick={() => setCurrentPage(p => Math.min(pageCount, p + 1))}
              disabled={currentPage >= pageCount}
              className="p-1 hover:text-sky-400 disabled:opacity-30 cursor-pointer"
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Zoom */}
          <div className="flex items-center gap-1 bg-slate-900 px-2 py-1 rounded-md border border-slate-800 text-xs">
            <button onClick={() => setZoomLevel(z => Math.max(0.6, z - 0.1))} className="p-1 hover:text-sky-400 cursor-pointer">
              <ZoomOut className="w-3.5 h-3.5" />
            </button>
            <span className="font-mono text-slate-300">{Math.round(zoomLevel * 100)}%</span>
            <button onClick={() => setZoomLevel(z => Math.min(1.8, z + 0.1))} className="p-1 hover:text-sky-400 cursor-pointer">
              <ZoomIn className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Side-by-Side Dual Pane */}
      <div className="grid grid-cols-2 flex-1 overflow-hidden divide-x divide-slate-800">
        {/* Left Pane: Original PDF with Bounding Box Overlays */}
        <div className="relative overflow-auto p-4 bg-slate-950 flex flex-col items-center">
          <div className="relative inline-block border border-slate-800 shadow-2xl rounded-sm bg-white">
            <img
              src={pageImageUrl}
              alt={`PDF Page ${currentPage}`}
              className="max-w-none block select-none pointer-events-none"
              style={{
                width: currentPageLayout ? `${currentPageLayout.width_pt * zoomLevel * 1.3}px` : '100%',
              }}
            />

            {/* SVG Overlay for System and Measure Bounding Boxes */}
            {currentPageLayout && (
              <svg
                className="absolute inset-0 w-full h-full pointer-events-auto"
                viewBox={`0 0 ${currentPageLayout.width_pt} ${currentPageLayout.height_pt}`}
              >
                {pageSystems.map((sys: any) => {
                  const sBox = sys.bounding_box
                  return (
                    <g key={`sys_${sys.system_index}`}>
                      <rect
                        x={sBox.x}
                        y={sBox.y}
                        width={sBox.w}
                        height={sBox.h}
                        fill="rgba(56, 189, 248, 0.03)"
                        stroke="rgba(56, 189, 248, 0.4)"
                        strokeWidth="1"
                        strokeDasharray="4 2"
                      />

                      {sys.measures?.map((m: any) => {
                        const mBox = m.bounding_box
                        const isSelected = selectedMeasureNumber === m.measure_number
                        const isPlaying = currentPlayingMeasure === m.measure_number

                        return (
                          <g
                            key={`m_${m.measure_number}`}
                            onClick={() => onSelectMeasure(m.measure_number)}
                            className="cursor-pointer group"
                          >
                            <rect
                              x={mBox.x}
                              y={mBox.y}
                              width={mBox.w}
                              height={mBox.h}
                              fill={
                                isPlaying
                                  ? 'rgba(234, 179, 8, 0.25)'
                                  : isSelected
                                  ? 'rgba(14, 165, 233, 0.22)'
                                  : 'rgba(0, 0, 0, 0.001)'
                              }
                              stroke={
                                isPlaying
                                  ? 'rgba(234, 179, 8, 0.9)'
                                  : isSelected
                                  ? 'rgba(14, 165, 233, 0.9)'
                                  : 'rgba(56, 189, 248, 0.2)'
                              }
                              strokeWidth={isSelected || isPlaying ? 2 : 0.8}
                              className="transition-all duration-150 group-hover:fill-sky-500/15 group-hover:stroke-sky-400"
                            />
                            <rect
                              x={mBox.x}
                              y={mBox.y - 12}
                              width={22}
                              height={11}
                              fill={isSelected ? '#0284c7' : '#0f172a'}
                              rx="2"
                            />
                            <text
                              x={mBox.x + 11}
                              y={mBox.y - 3}
                              fill="#f8fafc"
                              fontSize="8"
                              fontWeight="bold"
                              textAnchor="middle"
                              className="select-none font-mono"
                            >
                              {m.measure_number}
                            </text>
                          </g>
                        )
                      })}
                    </g>
                  )
                })}
              </svg>
            )}
          </div>
        </div>

        {/* Right Pane: OpenSheetMusicDisplay Rendered Score */}
        <div className="overflow-auto p-4 bg-white text-slate-900 relative">
          {!job.decoder_result && (
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-900/90 text-slate-300">
              <span className="text-sm font-mono animate-pulse">Awaiting MusicXML compilation...</span>
            </div>
          )}
          <div ref={osmdContainerRef} className="w-full" />
        </div>
      </div>
    </div>
  )
}
            <img
              src={pageImageUrl}
              alt={`PDF Page ${currentPage}`}
              className="max-w-none block select-none pointer-events-none"
              style={{
                width: currentPageLayout ? `${currentPageLayout.width_pt * zoomLevel * 1.3}px` : '100%',
              }}
            />

            {/* SVG Overlay for System and Measure Bounding Boxes */}
            {currentPageLayout && (
              <svg
                className="absolute inset-0 w-full h-full pointer-events-auto"
                viewBox={`0 0 ${currentPageLayout.width_pt} ${currentPageLayout.height_pt}`}
              >
                {pageSystems.map((sys: any) => {
                  const sBox = sys.bounding_box
                  return (
                    <g key={`sys_${sys.system_index}`}>
                      <rect
                        x={sBox.x}
                        y={sBox.y}
                        width={sBox.w}
                        height={sBox.h}
                        fill="rgba(56, 189, 248, 0.03)"
                        stroke="rgba(56, 189, 248, 0.4)"
                        strokeWidth="1"
                        strokeDasharray="4 2"
                      />

                      {sys.measures?.map((m: any) => {
                        const mBox = m.bounding_box
                        const isSelected = selectedMeasureNumber === m.measure_number
                        const isPlaying = currentPlayingMeasure === m.measure_number

                        return (
                          <g
                            key={`m_${m.measure_number}`}
                            onClick={() => onSelectMeasure(m.measure_number)}
                            className="cursor-pointer group"
                          >
                            <rect
                              x={mBox.x}
                              y={mBox.y}
                              width={mBox.w}
                              height={mBox.h}
                              fill={
                                isPlaying
                                  ? 'rgba(234, 179, 8, 0.25)'
                                  : isSelected
                                  ? 'rgba(14, 165, 233, 0.22)'
                                  : 'rgba(0, 0, 0, 0.001)'
                              }
                              stroke={
                                isPlaying
                                  ? 'rgba(234, 179, 8, 0.9)'
                                  : isSelected
                                  ? 'rgba(14, 165, 233, 0.9)'
                                  : 'rgba(56, 189, 248, 0.2)'
                              }
                              strokeWidth={isSelected || isPlaying ? 2 : 0.8}
                              className="transition-all duration-150 group-hover:fill-sky-500/15 group-hover:stroke-sky-400"
                            />
                            <rect
                              x={mBox.x}
                              y={mBox.y - 12}
                              width={22}
                              height={11}
                              fill={isSelected ? '#0284c7' : '#0f172a'}
                              rx="2"
                            />
                            <text
                              x={mBox.x + 11}
                              y={mBox.y - 3}
                              fill="#f8fafc"
                              fontSize="8"
                              fontWeight="bold"
                              textAnchor="middle"
                              className="select-none font-mono"
                            >
                              {m.measure_number}
                            </text>
                          </g>
                        )
                      })}
                    </g>
                  )
                })}
              </svg>
            )}
          </div>
        </div>

        {/* Right Pane: OpenSheetMusicDisplay Rendered Score */}
        <div className="overflow-auto p-4 bg-white text-slate-900 relative">
          {!job.decoder_result && (
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-900/90 text-slate-300">
              <span className="text-sm font-mono animate-pulse">Awaiting MusicXML compilation...</span>
            </div>
          )}
          <div ref={osmdContainerRef} className="w-full" />
        </div>
      </div>
    </div>
  )
}
