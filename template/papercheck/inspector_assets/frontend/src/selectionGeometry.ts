type ParagraphBox = Pick<HTMLElement, 'offsetLeft'|'offsetTop'|'offsetWidth'|'offsetHeight'>;

// Paper-relative offsets are stable while its scroll container moves.
export function paragraphBounds(target:ParagraphBox) {
  return {x:target.offsetLeft-1,y:target.offsetTop-1,width:target.offsetWidth+2,height:target.offsetHeight+2};
}
