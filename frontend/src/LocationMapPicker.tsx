import { useEffect } from "react";
import { divIcon } from "leaflet";
import { MapContainer, Marker, TileLayer, useMap, useMapEvents } from "react-leaflet";
import "leaflet/dist/leaflet.css";

type Props={latitude?:number;longitude?:number;onPick:(latitude:number,longitude:number)=>void};
const markerIcon=divIcon({className:"corv-map-marker",html:"<span></span>",iconSize:[24,24],iconAnchor:[12,24]});

function ClickPicker({onPick}:{onPick:Props["onPick"]}){useMapEvents({click(event){onPick(Number(event.latlng.lat.toFixed(6)),Number(event.latlng.lng.toFixed(6)))}});return null}
function SyncView({latitude,longitude}:{latitude?:number;longitude?:number}){const map=useMap();useEffect(()=>{if(Number.isFinite(latitude)&&Number.isFinite(longitude))map.setView([latitude!,longitude!],Math.max(map.getZoom(),15))},[map,latitude,longitude]);return null}

export default function LocationMapPicker({latitude,longitude,onPick}:Props){const selected=Number.isFinite(latitude)&&Number.isFinite(longitude);return <div className="clickable-location-map"><MapContainer center={selected?[latitude!,longitude!]:[25,0]} zoom={selected?15:2} scrollWheelZoom aria-label="Click map to choose coordinates"><TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"/><ClickPicker onPick={onPick}/><SyncView latitude={latitude} longitude={longitude}/>{selected&&<Marker position={[latitude!,longitude!]} icon={markerIcon}/>}</MapContainer><p>Click or tap the map to place the marker.</p></div>}
